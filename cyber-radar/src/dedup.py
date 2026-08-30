"""Dedup mantığı.

Akademik tarafta gerçek anahtar DOI / arXiv ID / OpenAlex ID (DB'de UNIQUE
kolonlar bunu zaten garanti eder); normalized_title ise bu ID'ler eksikse
ikinci bir güvenlik ağı olarak kullanılır.

Haber tarafında ise "aynı olayın 20 kaynağı = 1 event, 20 source" prensibi
burada uygulanır: canonical URL, CVE kesişimi ve başlık benzerliğiyle mevcut
bir news_events satırına mı ekleniyoruz yoksa yeni satır mı açılıyor karar
verilir.
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode

_TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "ref", "ref_src", "fbclid", "gclid", "mc_cid", "mc_eid",
}

_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)
_WS_RE = re.compile(r"\s+")


def normalize_title(title: str) -> str:
    """Başlığı karşılaştırılabilir hale getirir: küçük harf, noktalama yok,
    tekrarlayan boşluklar tek boşluğa indirilir."""
    if not title:
        return ""
    t = title.lower().strip()
    t = _PUNCT_RE.sub(" ", t)
    t = _WS_RE.sub(" ", t)
    return t.strip()


def canonical_url(url: str) -> str:
    """Tracking parametrelerini temizler, host'u küçük harfe çevirir,
    sondaki / işaretini kaldırır."""
    if not url:
        return url
    parsed = urlparse(url)
    query = [(k, v) for k, v in parse_qsl(parsed.query) if k.lower() not in _TRACKING_PARAMS]
    path = parsed.path.rstrip("/") or "/"
    cleaned = parsed._replace(
        netloc=parsed.netloc.lower(),
        path=path,
        query=urlencode(query),
        fragment="",
    )
    return urlunparse(cleaned)


def title_similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, normalize_title(a), normalize_title(b)).ratio()


def extract_cves(text: str) -> list[str]:
    if not text:
        return []
    return sorted(set(re.findall(r"CVE-\d{4}-\d{4,7}", text, flags=re.IGNORECASE)), key=str.upper)


def is_same_event(
    new_title: str,
    new_cves: list[str],
    new_url: str,
    existing_title: str,
    existing_cves: list[str],
    existing_urls: list[str],
    title_threshold: float = 0.72,
) -> bool:
    """Bir haberin mevcut bir news_events satırıyla aynı olay olup olmadığına
    karar verir. Sinyaller: aynı canonical URL, ortak CVE, veya yüksek başlık
    benzerliği. Orijinal mimari dokümanındaki dedup sinyallerinin (CVE, ürün,
    vendor, başlık benzerliği) basitleştirilmiş, tek-sunucuya uygun hali."""
    if new_url and canonical_url(new_url) in {canonical_url(u) for u in existing_urls}:
        return True
    if new_cves and existing_cves and set(new_cves) & set(existing_cves):
        return True
    if title_similarity(new_title, existing_title) >= title_threshold:
        return True
    return False
