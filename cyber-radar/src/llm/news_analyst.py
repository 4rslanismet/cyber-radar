"""Level 3: Derin haber analizi + entity extraction.

Öncelik skoru (priority_score) bilinçli olarak LLM'e bırakılmadı - orijinal
mimari dokümanındaki sabit puan tablosu deterministik ve tutarlı olduğu için
klasik Python fonksiyonuyla hesaplanıyor (bkz. Tasarım İlkesi: "muhakeme
gerektirmeyen işler klasik servislere bırakılır"). LLM sadece CVE/aktör/
malware gibi entity'leri metinden çıkarmak için kullanılıyor.
"""
from __future__ import annotations

from .. import config
from .client import call_json

_SYSTEM = """Sen bir siber tehdit istihbaratı analistisin. Görevin verilen
haberden yapılandırılmış bilgi çıkarmak.

ÖNEMLİ PRENSİP: Tek bir haber sitesinin iddiası doğrulanmış teknik gerçek
değildir. "active_exploitation" veya "zero_day" gibi alanları yalnızca metin
bunu AÇIKÇA belirtiyorsa true yap; metin belirsizse false bırak ve
"evidence_note" alanına neden emin olmadığını yaz.

Metinde belirtilmeyen bilgiyi uydurma; ilgili alanı boş liste veya null bırak.

Yalnızca şu şemada geçerli JSON döndür, başka hiçbir metin ekleme:
{
  "summary": string,
  "event_type": string,             // VULNERABILITY|ZERO_DAY|MALWARE|RANSOMWARE|APT|DATA_BREACH|PHISHING|SUPPLY_CHAIN|diğer
  "vendors": [string],
  "products": [string],
  "cves": [string],
  "cwe": [string],
  "exploit_status": string | null,  // "poc"|"active_exploitation"|"none_reported"|null
  "zero_day": boolean,
  "active_exploitation": boolean,
  "evidence_note": string | null,
  "malware": [string],
  "threat_actors": [string],
  "campaigns": [string],
  "target_sectors": [string],
  "target_countries": [string],
  "mitre_attack": [string],
  "attack_vector": string | null,
  "impact": string | null,
  "mitigation": [string],
  "detection": [string]
}"""


def analyze_news(title: str, raw_text: str) -> dict:
    content = f"Başlık: {title}\n\nİçerik: {raw_text[:20000]}"
    return call_json(config.ANALYSIS_MODEL, _SYSTEM, content, max_output_tokens=2000)


# ---------------------------------------------------------------------------
# Deterministik öncelik skoru (bkz. proje notları bölüm 19)
# ---------------------------------------------------------------------------
_WEIGHTS = {
    "cisa_kev": 30,
    "active_exploitation": 25,
    "zero_day": 20,
    "remote_code_execution": 15,
    "authentication_bypass": 15,
    "ransomware_use": 15,
    "internet_facing": 10,
    "critical_infra": 10,
}


def compute_priority(analysis: dict, cisa_kev: bool) -> tuple[int, str]:
    score = 0
    reasons: list[str] = []

    if cisa_kev:
        score += _WEIGHTS["cisa_kev"]
        reasons.append("CISA KEV")
    if analysis.get("active_exploitation"):
        score += _WEIGHTS["active_exploitation"]
        reasons.append("Active exploitation")
    if analysis.get("zero_day"):
        score += _WEIGHTS["zero_day"]
        reasons.append("Zero-day")

    impact_text = " ".join(
        [
            str(analysis.get("attack_vector") or ""),
            str(analysis.get("impact") or ""),
            str(analysis.get("event_type") or ""),
        ]
    ).lower()

    if "remote code execution" in impact_text or "rce" in impact_text:
        score += _WEIGHTS["remote_code_execution"]
        reasons.append("Remote code execution")
    if "authentication bypass" in impact_text or "auth bypass" in impact_text:
        score += _WEIGHTS["authentication_bypass"]
        reasons.append("Authentication bypass")
    if analysis.get("event_type") == "RANSOMWARE" or "ransomware" in impact_text:
        score += _WEIGHTS["ransomware_use"]
        reasons.append("Ransomware")
    if any(s.lower() in ("critical infrastructure", "ics", "ot", "energy", "healthcare")
           for s in (analysis.get("target_sectors") or [])):
        score += _WEIGHTS["critical_infra"]
        reasons.append("Critical infrastructure impact")
    if "internet-facing" in impact_text or "internet facing" in impact_text or "publicly accessible" in impact_text:
        score += _WEIGHTS["internet_facing"]
        reasons.append("Internet-facing product")

    score = min(score, 100)

    if score >= 80:
        label = "CRITICAL"
    elif score >= 55:
        label = "HIGH"
    elif score >= 30:
        label = "MEDIUM"
    else:
        label = "LOW"

    return score, label
