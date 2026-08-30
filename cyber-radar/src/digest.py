"""Brifing üretici - orijinal mimari dokümanındaki (bölüm 26) şablonun
sadeleştirilmiş, gerçek veriden üretilen hali."""
from __future__ import annotations

import os
from datetime import datetime
from typing import Any

from . import config


def generate_brief(
    news_events: list[dict[str, Any]],
    papers: list[dict[str, Any]],
    notebooklm_updates: dict[str, list[str]],
    slot: str,
) -> str:
    """slot: 'Sabah' | 'Akşam' - yalnızca başlıkta görünür."""
    now = datetime.now()
    lines = [
        f"# Cyber Intelligence Radar — {slot} Brifingi",
        f"_{now.strftime('%Y-%m-%d %H:%M')}_",
        "",
    ]

    critical = [n for n in news_events if (n.get("priority_label") in ("CRITICAL", "HIGH"))]
    other_news = [n for n in news_events if n not in critical]

    lines.append("## Kritik / Yüksek Öncelikli Olaylar")
    if critical:
        for n in critical:
            cves = ", ".join(n.get("cves") or []) or "-"
            lines.append(
                f"- **[{n.get('priority_label')}] {n.get('title')}** "
                f"(skor {n.get('priority_score')}, CVE: {cves})"
            )
    else:
        lines.append("_Bu dönemde kritik/yüksek öncelikli olay yok._")
    lines.append("")

    lines.append("## Diğer Tehdit İstihbaratı")
    if other_news:
        for n in other_news[:15]:
            lines.append(f"- {n.get('title')} ({n.get('priority_label', 'LOW')})")
    else:
        lines.append("_Bu dönemde başka ilgili haber yok._")
    lines.append("")

    lines.append("## Yeni Akademik Makaleler")
    if papers:
        for p in papers:
            score = ((p.get("analysis") or {}).get("academic_value_score"))
            score_txt = f", değer skoru {score}" if score is not None else ""
            lines.append(f"- {p.get('title')} ({p.get('analysis_type')}{score_txt})")
    else:
        lines.append("_Bu dönemde yeni ilgili makale yok._")
    lines.append("")

    if notebooklm_updates:
        lines.append("## NotebookLM İçin Güncellenen Dosyalar")
        lines.append("_Aşağıdaki dosyaları ilgili NotebookLM notebook'unuza manuel yükleyin:_")
        for topic, files in notebooklm_updates.items():
            for f in files:
                lines.append(f"- **{topic}**: `{f}`")
        lines.append("")

    review_count = sum(1 for n in news_events if n.get("relevance_status") == "uncertain") + sum(
        1 for p in papers if p.get("relevance_status") == "uncertain"
    )
    if review_count:
        lines.append(f"## Gözden Geçirme Kuyruğu\n{review_count} öğe belirsiz kategoride, review_queue tablosunda bekliyor.\n")

    return "\n".join(lines)


def save_brief(text: str, slot: str) -> str:
    os.makedirs(config.REPORTS_DIR, exist_ok=True)
    filename = f"{datetime.now().strftime('%Y-%m-%d')}_{slot.lower()}.md"
    path = os.path.join(config.REPORTS_DIR, filename)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path
