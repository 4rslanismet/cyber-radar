"""Cyber Intelligence Radar - ana pipeline.

Çalıştırma: proje kök dizininden
    python3 -m src.run_pipeline

Akış: topla -> dedup -> ilgililik filtrele -> derin analiz -> NotebookLM
export -> brifing üret -> Telegram'a gönder -> pipeline_state güncelle.

Her adım kendi try/except'iyle sarılı: tek bir kaynağın/feed'in çökmesi tüm
koşuyu düşürmez, hata collector_runs tablosuna loglanır.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from . import config, db, digest, notify, notebooklm_export
from .collectors import academic, news as news_collector
from .dedup import is_same_event, normalize_title
from .llm import news_analyst, paper_analyst, relevance


# ---------------------------------------------------------------------------
# Akademik: upsert + dedup
# ---------------------------------------------------------------------------
def _upsert_paper(conn, item: dict) -> None:
    norm_title = normalize_title(item.get("title", ""))
    if not norm_title:
        return

    existing = conn.execute(
        """
        SELECT id, source_apis FROM papers
        WHERE (doi IS NOT NULL AND doi = %(doi)s)
           OR (arxiv_id IS NOT NULL AND arxiv_id = %(arxiv_id)s)
           OR (openalex_id IS NOT NULL AND openalex_id = %(openalex_id)s)
           OR normalized_title = %(norm_title)s
        LIMIT 1
        """,
        {
            "doi": item.get("doi"),
            "arxiv_id": item.get("arxiv_id"),
            "openalex_id": item.get("openalex_id"),
            "norm_title": norm_title,
        },
    ).fetchone()

    if existing:
        source_apis = sorted(set(existing["source_apis"] or []) | {item["source_api"]})
        conn.execute("UPDATE papers SET source_apis = %s WHERE id = %s", (source_apis, existing["id"]))
        return

    conn.execute(
        """
        INSERT INTO papers (doi, arxiv_id, openalex_id, title, normalized_title, authors,
                             venue, publication_date, abstract, pdf_url, source_apis)
        VALUES (%(doi)s, %(arxiv_id)s, %(openalex_id)s, %(title)s, %(norm_title)s, %(authors)s::jsonb,
                %(venue)s, %(publication_date)s, %(abstract)s, %(pdf_url)s, %(source_apis)s)
        """,
        {
            "doi": item.get("doi"),
            "arxiv_id": item.get("arxiv_id"),
            "openalex_id": item.get("openalex_id"),
            "title": (item.get("title") or "")[:1000],
            "norm_title": norm_title,
            "authors": db.to_jsonb(item.get("authors") or []),
            "venue": item.get("venue"),
            "publication_date": item.get("publication_date") or None,
            "abstract": item.get("abstract"),
            "pdf_url": item.get("pdf_url"),
            "source_apis": [item["source_api"]],
        },
    )


# ---------------------------------------------------------------------------
# Haber: aynı olayı birleştir ya da yeni event aç
# ---------------------------------------------------------------------------
def _find_or_merge_news_event(conn, item: dict) -> None:
    window_start = datetime.now(timezone.utc) - timedelta(days=14)
    candidates = conn.execute(
        "SELECT id, title, cves, sources FROM news_events WHERE first_seen_at >= %s",
        (window_start,),
    ).fetchall()

    for cand in candidates:
        existing_urls = [s.get("url", "") for s in (cand["sources"] or [])]
        if is_same_event(item["title"], item["cves"], item["url"], cand["title"], cand["cves"] or [], existing_urls):
            sources = cand["sources"] or []
            if item["url"] and not any(s.get("url") == item["url"] for s in sources):
                sources.append({"name": item["source"], "url": item["url"]})
            merged_cves = sorted(set((cand["cves"] or []) + item["cves"]))
            conn.execute(
                """
                UPDATE news_events
                SET sources = %s::jsonb, cves = %s, last_updated_at = now()
                WHERE id = %s
                """,
                (db.to_jsonb(sources), merged_cves, cand["id"]),
            )
            return

    conn.execute(
        """
        INSERT INTO news_events (title, dedup_key, summary, sources, published_at, raw_text, cves)
        VALUES (%(title)s, %(dedup_key)s, %(summary)s, %(sources)s::jsonb, %(published_at)s,
                %(raw_text)s, %(cves)s)
        """,
        {
            "title": item["title"][:1000],
            "dedup_key": normalize_title(item["title"]),
            "summary": item["summary"],
            "sources": db.to_jsonb([{"name": item["source"], "url": item["url"]}]),
            "published_at": item.get("published_at"),
            "raw_text": item["raw_text"],
            "cves": item["cves"],
        },
    )


# ---------------------------------------------------------------------------
# Relevance filtresi
# ---------------------------------------------------------------------------
def _classify_pending_papers(conn) -> None:
    rows = conn.execute("SELECT id, title, abstract FROM papers WHERE relevance_status = 'pending'").fetchall()
    for r in rows:
        try:
            result, status = relevance.classify_paper(r["title"], r["abstract"])
        except Exception as e:  # noqa: BLE001 - tek makale hatası koşuyu durdurmasın
            db.log_collector_run(conn, "relevance_llm", "academic", (r["title"] or "")[:200], None, str(e))
            continue
        conn.execute(
            "UPDATE papers SET relevance = %s::jsonb, relevance_status = %s WHERE id = %s",
            (db.to_jsonb(result), status, r["id"]),
        )
        if status == "uncertain":
            conn.execute(
                "INSERT INTO review_queue (item_type, item_id, reason, confidence) VALUES ('paper', %s, %s, %s)",
                (r["id"], "relevance_uncertain", result.get("confidence")),
            )


def _classify_pending_news(conn) -> None:
    rows = conn.execute("SELECT id, title, summary FROM news_events WHERE relevance_status = 'pending'").fetchall()
    for r in rows:
        try:
            result, status = relevance.classify_news(r["title"], r["summary"])
        except Exception as e:  # noqa: BLE001
            db.log_collector_run(conn, "relevance_llm", "news", (r["title"] or "")[:200], None, str(e))
            continue
        conn.execute(
            "UPDATE news_events SET relevance = %s::jsonb, relevance_status = %s WHERE id = %s",
            (db.to_jsonb(result), status, r["id"]),
        )
        if status == "uncertain":
            conn.execute(
                "INSERT INTO review_queue (item_type, item_id, reason, confidence) VALUES ('news', %s, %s, %s)",
                (r["id"], "relevance_uncertain", result.get("confidence")),
            )


# ---------------------------------------------------------------------------
# Derin analiz
# ---------------------------------------------------------------------------
def _analyze_relevant_papers(conn) -> list[dict]:
    rows = conn.execute(
        "SELECT id, title, doi, arxiv_id, abstract FROM papers "
        "WHERE relevance_status = 'relevant' AND analyzed_at IS NULL"
    ).fetchall()

    analyzed: list[dict] = []
    for r in rows:
        pdf_url, pdf_source = academic.resolve_pdf(r["doi"], r["arxiv_id"])
        full_text, pdf_local, analysis_type = None, None, "ABSTRACT_ONLY"
        if pdf_url:
            key = (r["doi"] or r["arxiv_id"] or str(r["id"])).replace("/", "_")
            try:
                pdf_local, full_text = academic.download_and_extract_pdf(pdf_url, key)
            except Exception:
                pdf_local, full_text = None, None
            if full_text:
                analysis_type = "FULL_TEXT"

        try:
            analysis = paper_analyst.analyze_paper(r["title"], r["abstract"], full_text, analysis_type)
        except Exception as e:  # noqa: BLE001
            db.log_collector_run(conn, "analysis_llm", "academic", (r["title"] or "")[:200], None, str(e))
            continue

        conn.execute(
            """
            UPDATE papers
            SET analysis = %s::jsonb, analyzed_at = now(), analysis_type = %s,
                pdf_url = COALESCE(%s, pdf_url), pdf_local_path = %s, pdf_source = %s
            WHERE id = %s
            """,
            (db.to_jsonb(analysis), analysis_type, pdf_url, pdf_local, pdf_source, r["id"]),
        )
        full_row = conn.execute("SELECT * FROM papers WHERE id = %s", (r["id"],)).fetchone()
        analyzed.append(full_row)
    return analyzed


def _analyze_relevant_news(conn, kev_set: set[str]) -> list[dict]:
    rows = conn.execute(
        "SELECT id, title, raw_text, cves FROM news_events "
        "WHERE relevance_status = 'relevant' AND analyzed_at IS NULL"
    ).fetchall()

    analyzed: list[dict] = []
    for r in rows:
        try:
            analysis = news_analyst.analyze_news(r["title"], r["raw_text"] or "")
        except Exception as e:  # noqa: BLE001
            db.log_collector_run(conn, "analysis_llm", "news", (r["title"] or "")[:200], None, str(e))
            continue

        merged_cves = sorted(set((r["cves"] or []) + (analysis.get("cves") or [])))
        is_kev = bool(set(merged_cves) & kev_set)
        score, label = news_analyst.compute_priority(analysis, is_kev)

        conn.execute(
            """
            UPDATE news_events
            SET analysis = %s::jsonb, analyzed_at = now(), cves = %s,
                vendors = %s, products = %s, cisa_kev = %s,
                priority_score = %s, priority_label = %s
            WHERE id = %s
            """,
            (
                db.to_jsonb(analysis), merged_cves,
                analysis.get("vendors") or [], analysis.get("products") or [],
                is_kev, score, label, r["id"],
            ),
        )
        full_row = conn.execute("SELECT * FROM news_events WHERE id = %s", (r["id"],)).fetchone()
        analyzed.append(full_row)
    return analyzed


# ---------------------------------------------------------------------------
# NotebookLM export
# ---------------------------------------------------------------------------
def _export_to_notebooklm(conn, analyzed_papers: list[dict]) -> dict[str, list[str]]:
    updated: dict[str, list[str]] = {}
    for p in analyzed_papers:
        if p.get("notebooklm_topic"):
            continue
        result = notebooklm_export.export_paper(p)
        if not result:
            continue
        topic, file_path = result
        conn.execute("UPDATE papers SET notebooklm_topic = %s WHERE id = %s", (topic, p["id"]))
        updated.setdefault(topic, [])
        if file_path not in updated[topic]:
            updated[topic].append(file_path)
    return updated


# ---------------------------------------------------------------------------
# Coverage audit: bu koşu bir öncekine göre çok mu az sonuç getirdi?
# ---------------------------------------------------------------------------
def _coverage_warning(conn, this_run_total: int) -> str | None:
    row = conn.execute(
        """
        SELECT COALESCE(SUM(result_count), 0) AS prev_total
        FROM collector_runs
        WHERE finished_at >= now() - interval '36 hours'
          AND finished_at < now() - interval '10 hours'
        """
    ).fetchone()
    prev_total = row["prev_total"] if row else 0
    if prev_total and this_run_total < prev_total * 0.3:
        return (
            f"⚠️ Bu koşuda toplam {this_run_total} sonuç geldi, önceki koşuda {prev_total} idi. "
            f"Bir kaynak/feed bozulmuş olabilir - collector_runs tablosunu kontrol edin."
        )
    return None


def main() -> None:
    slot = "Sabah" if datetime.now().hour < 13 else "Akşam"
    run_result_total = 0

    with db.get_conn() as conn:
        last_run_str = db.get_state(conn, "last_run_at")
        since_dt = (
            datetime.fromisoformat(last_run_str)
            if last_run_str
            else datetime.now(timezone.utc) - timedelta(hours=24)
        )
        since_date: date = since_dt.date()

        # 1) Akademik toplama - her anahtar kelime, her kaynağa paralel (sıralı) soruluyor
        for keyword in config.KEYWORDS:
            for name, fn in academic.COLLECTORS.items():
                try:
                    items = fn(keyword, since_date)
                    for item in items:
                        _upsert_paper(conn, item)
                    db.log_collector_run(conn, name, "academic", keyword, len(items))
                    run_result_total += len(items)
                except Exception as e:  # noqa: BLE001
                    db.log_collector_run(conn, name, "academic", keyword, None, str(e))

        # 2) Haber toplama
        for feed_url in config.NEWS_FEEDS:
            try:
                items = news_collector.fetch_rss_feed(feed_url, since_date)
                for item in items:
                    _find_or_merge_news_event(conn, item)
                db.log_collector_run(conn, feed_url, "news", None, len(items))
                run_result_total += len(items)
            except Exception as e:  # noqa: BLE001
                db.log_collector_run(conn, feed_url, "news", None, None, str(e))

        kev_set = news_collector.fetch_cisa_kev()

        # 3) İlgililik filtresi (Level 1 - ucuz model)
        _classify_pending_papers(conn)
        _classify_pending_news(conn)

        # 4) Derin analiz (Level 3-4 - güçlü model, sadece 'relevant' olanlar)
        analyzed_papers = _analyze_relevant_papers(conn)
        analyzed_news = _analyze_relevant_news(conn, kev_set)

        # 5) NotebookLM export
        nb_updates = _export_to_notebooklm(conn, analyzed_papers)

        # 6) Brifing üret + gönder
        brief = digest.generate_brief(analyzed_news, analyzed_papers, nb_updates, slot)
        warning = _coverage_warning(conn, run_result_total)
        if warning:
            brief = f"{warning}\n\n{brief}"
        digest.save_brief(brief, slot)
        sent = notify.send_telegram(brief)

        db.set_state(conn, "last_run_at", datetime.now(timezone.utc).isoformat())

    print(brief)
    if not sent:
        print("\n[UYARI] Telegram bildirimi gönderilemedi - .env içindeki TELEGRAM_* değerlerini kontrol edin.")


if __name__ == "__main__":
    main()
