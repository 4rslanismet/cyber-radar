"""Akademik makale toplayıcılar.

Her fonksiyon aynı normalize sözlük şeklini döndürür:
{title, authors[], doi, arxiv_id, openalex_id, venue, publication_date,
 abstract, pdf_url, source_api}

Tasarım ilkesi (bkz. proje notları): "kaçırmamak" için tek kaynağa güvenmiyoruz,
aynı anahtar kelimeyi 4 kaynağa paralel soruyoruz; dedup katmanı DOI/arXiv ID
üzerinden DB'de zaten hallediyor.

Not: Bu fonksiyonlar gerçek API uç noktalarını kullanır ancak bu ortamda ağ
erişimi kapalı olduğu için test edilememiştir - kendi sunucunuzda ilk koşuda
`--dry-run` ile (bkz. run_pipeline.py) tek tek doğrulamanızı öneririz. Kaynak
siteler zaman zaman endpoint/parametre değiştirebilir.
"""
from __future__ import annotations

import os
import xml.etree.ElementTree as ET
from datetime import date
from typing import Any

import fitz  # PyMuPDF
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from .. import config

_TIMEOUT = httpx.Timeout(20.0)
_ARXIV_NS = {"atom": "http://www.w3.org/2005/Atom"}


def _retry_get(url: str, **kwargs) -> httpx.Response:
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=15))
    def _do() -> httpx.Response:
        resp = httpx.get(url, timeout=_TIMEOUT, **kwargs)
        resp.raise_for_status()
        return resp

    return _do()


def search_openalex(keyword: str, since: date, per_page: int = 25) -> list[dict[str, Any]]:
    """https://docs.openalex.org/api-entities/works/search-works"""
    params = {
        "search": keyword,
        "filter": f"from_publication_date:{since.isoformat()}",
        "per-page": per_page,
        "sort": "publication_date:desc",
    }
    if config.CONTACT_EMAIL:
        params["mailto"] = config.CONTACT_EMAIL

    resp = _retry_get("https://api.openalex.org/works", params=params)
    results = []
    for w in resp.json().get("results", []):
        oa = w.get("open_access") or {}
        results.append({
            "title": w.get("title") or "",
            "authors": [
                a.get("author", {}).get("display_name", "")
                for a in w.get("authorships", [])
                if a.get("author")
            ],
            "doi": (w.get("doi") or "").replace("https://doi.org/", "") or None,
            "arxiv_id": None,
            "openalex_id": w.get("id"),
            "venue": (w.get("primary_location") or {}).get("source", {}).get("display_name")
                if (w.get("primary_location") or {}).get("source") else None,
            "publication_date": w.get("publication_date"),
            "abstract": _reconstruct_openalex_abstract(w.get("abstract_inverted_index")),
            "pdf_url": oa.get("oa_url"),
            "source_api": "openalex",
        })
    return results


def _reconstruct_openalex_abstract(inverted_index: dict[str, list[int]] | None) -> str | None:
    """OpenAlex abstract'ı ters index olarak döner (telif nedeniyle); burada
    düz metne geri çeviriyoruz."""
    if not inverted_index:
        return None
    positions: dict[int, str] = {}
    for word, idxs in inverted_index.items():
        for i in idxs:
            positions[i] = word
    if not positions:
        return None
    return " ".join(positions[i] for i in sorted(positions))


def search_crossref(keyword: str, since: date, rows: int = 25) -> list[dict[str, Any]]:
    """https://api.crossref.org/swagger-ui/index.html"""
    params = {
        "query": keyword,
        "filter": f"from-pub-date:{since.isoformat()}",
        "rows": rows,
        "sort": "published",
        "order": "desc",
    }
    headers = {}
    if config.CONTACT_EMAIL:
        headers["User-Agent"] = f"CyberIntelligenceRadar/0.1 (mailto:{config.CONTACT_EMAIL})"

    resp = _retry_get("https://api.crossref.org/works", params=params, headers=headers)
    results = []
    for item in resp.json().get("message", {}).get("items", []):
        date_parts = (item.get("published") or item.get("issued") or {}).get("date-parts", [[None]])
        pub_date = _date_parts_to_iso(date_parts[0]) if date_parts else None
        results.append({
            "title": (item.get("title") or [""])[0],
            "authors": [
                f"{a.get('given', '')} {a.get('family', '')}".strip()
                for a in item.get("author", [])
            ],
            "doi": item.get("DOI"),
            "arxiv_id": None,
            "openalex_id": None,
            "venue": (item.get("container-title") or [None])[0],
            "publication_date": pub_date,
            "abstract": item.get("abstract"),
            "pdf_url": None,
            "source_api": "crossref",
        })
    return results


def _date_parts_to_iso(parts: list[int | None]) -> str | None:
    if not parts or parts[0] is None:
        return None
    y = parts[0]
    m = parts[1] if len(parts) > 1 else 1
    d = parts[2] if len(parts) > 2 else 1
    try:
        return date(y, m or 1, d or 1).isoformat()
    except ValueError:
        return f"{y:04d}-01-01"


def search_arxiv(keyword: str, since: date, max_results: int = 25) -> list[dict[str, Any]]:
    """https://info.arxiv.org/help/api/user-manual.html
    arXiv API tarih filtresi desteklemiyor; en yeniye göre sıralayıp
    sonradan `since` ile Python tarafında filtreliyoruz."""
    params = {
        "search_query": f'all:"{keyword}" AND cat:cs.CR',
        "sortBy": "submittedDate",
        "sortOrder": "descending",
        "max_results": max_results,
    }
    resp = _retry_get("http://export.arxiv.org/api/query", params=params)
    root = ET.fromstring(resp.text)
    results = []
    for entry in root.findall("atom:entry", _ARXIV_NS):
        published = entry.findtext("atom:published", default="", namespaces=_ARXIV_NS)
        pub_date = published[:10] if published else None
        if pub_date and pub_date < since.isoformat():
            continue
        arxiv_url = entry.findtext("atom:id", default="", namespaces=_ARXIV_NS)
        arxiv_id = arxiv_url.rsplit("/", 1)[-1] if arxiv_url else None
        pdf_url = None
        for link in entry.findall("atom:link", _ARXIV_NS):
            if link.get("title") == "pdf":
                pdf_url = link.get("href")
        results.append({
            "title": (entry.findtext("atom:title", default="", namespaces=_ARXIV_NS) or "").strip(),
            "authors": [
                a.findtext("atom:name", default="", namespaces=_ARXIV_NS)
                for a in entry.findall("atom:author", _ARXIV_NS)
            ],
            "doi": None,
            "arxiv_id": arxiv_id,
            "openalex_id": None,
            "venue": "arXiv",
            "publication_date": pub_date,
            "abstract": (entry.findtext("atom:summary", default="", namespaces=_ARXIV_NS) or "").strip(),
            "pdf_url": pdf_url,
            "source_api": "arxiv",
        })
    return results


def search_semantic_scholar(keyword: str, since: date, limit: int = 25) -> list[dict[str, Any]]:
    """https://api.semanticscholar.org/api-docs/graph"""
    headers = {}
    if config.SEMANTIC_SCHOLAR_API_KEY:
        headers["x-api-key"] = config.SEMANTIC_SCHOLAR_API_KEY

    params = {
        "query": keyword,
        "limit": limit,
        "fields": "title,authors,externalIds,venue,publicationDate,abstract,openAccessPdf",
        "publicationDateOrYear": f"{since.isoformat()}:",
    }
    resp = _retry_get(
        "https://api.semanticscholar.org/graph/v1/paper/search",
        params=params,
        headers=headers,
    )
    results = []
    for p in resp.json().get("data", []):
        ext = p.get("externalIds") or {}
        oa_pdf = p.get("openAccessPdf") or {}
        results.append({
            "title": p.get("title") or "",
            "authors": [a.get("name", "") for a in p.get("authors", [])],
            "doi": ext.get("DOI"),
            "arxiv_id": ext.get("ArXiv"),
            "openalex_id": None,
            "venue": p.get("venue"),
            "publication_date": p.get("publicationDate"),
            "abstract": p.get("abstract"),
            "pdf_url": oa_pdf.get("url"),
            "source_api": "semantic_scholar",
        })
    return results


def resolve_pdf(doi: str | None, arxiv_id: str | None) -> tuple[str | None, str | None]:
    """FULL_TEXT çözümleme: önce Unpaywall (DOI varsa), sonra arXiv PDF linki.
    Paywall bypass yapılmaz - sadece açık erişim sürümleri aranır.
    Döner: (pdf_url, source) ya da (None, None)."""
    if doi and config.CONTACT_EMAIL:
        try:
            resp = _retry_get(
                f"https://api.unpaywall.org/v2/{doi}",
                params={"email": config.CONTACT_EMAIL},
            )
            data = resp.json()
            best = data.get("best_oa_location") or {}
            if best.get("url_for_pdf"):
                return best["url_for_pdf"], "unpaywall"
        except httpx.HTTPError:
            pass
    if arxiv_id:
        return f"https://arxiv.org/pdf/{arxiv_id}", "arxiv"
    return None, None


def download_and_extract_pdf(pdf_url: str, paper_key: str) -> tuple[str | None, str | None]:
    """PDF'i indirir, diske kaydeder (data/academic/pdf/{key}.pdf) ve
    PyMuPDF ile düz metne çevirir. Başarısız olursa (None, None) döner -
    bu durumda çağıran taraf ABSTRACT_ONLY seviyesinde devam eder.
    Döner: (local_path, extracted_text)"""
    try:
        resp = httpx.get(pdf_url, timeout=_TIMEOUT, follow_redirects=True)
        resp.raise_for_status()
    except httpx.HTTPError:
        return None, None

    content_type = resp.headers.get("content-type", "").lower()
    if "pdf" not in content_type and not pdf_url.lower().endswith(".pdf"):
        return None, None

    os.makedirs(config.PDF_DIR, exist_ok=True)
    safe_key = "".join(c if c.isalnum() or c in "-._" else "_" for c in paper_key)[:150]
    local_path = os.path.join(config.PDF_DIR, f"{safe_key}.pdf")
    with open(local_path, "wb") as f:
        f.write(resp.content)

    try:
        doc = fitz.open(local_path)
        text = "\n".join(page.get_text() for page in doc)
        doc.close()
    except Exception:
        text = None

    return local_path, (text or None)


COLLECTORS = {
    "openalex": search_openalex,
    "crossref": search_crossref,
    "arxiv": search_arxiv,
    "semantic_scholar": search_semantic_scholar,
}
