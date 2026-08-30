"""Merkezi konfigürasyon. .env dosyasını okur, her modül buradan import eder."""
from __future__ import annotations

import os
from dotenv import load_dotenv

load_dotenv()


def _list_env(name: str, default: str = "") -> list[str]:
    raw = os.getenv(name, default)
    return [item.strip() for item in raw.split(",") if item.strip()]


DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://radar:radar@localhost:5432/cyber_radar")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
# Ucuz/hızlı katman (relevance filtresi). Bu isim doğrulanmış güncel bir flash
# modeli - https://ai.google.dev/gemini-api/docs/models sayfasından teyit edin.
RELEVANCE_MODEL = os.getenv("RELEVANCE_MODEL", "gemini-3.7-flash")
# Derin analiz katmanı. Google'ın "pro" seri model adları sık değişiyor
# (gemini-3-pro-preview kapatıldı, yerine gemini-3.1-pro-preview vb. geldi).
# Bilinçli olarak burada da flash varsayılan bırakıldı ki kutudan çıktığında
# çalışsın; daha güçlü akıl yürütme istiyorsanız güncel pro model adını
# yukarıdaki sayfadan kontrol edip .env içinde ANALYSIS_MODEL'i değiştirin.
ANALYSIS_MODEL = os.getenv("ANALYSIS_MODEL", "gemini-3.7-flash")

CONTACT_EMAIL = os.getenv("CONTACT_EMAIL", "")
SEMANTIC_SCHOLAR_API_KEY = os.getenv("SEMANTIC_SCHOLAR_API_KEY", "")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

KEYWORDS = _list_env("KEYWORDS", "cybersecurity")
NEWS_FEEDS = _list_env("NEWS_FEEDS", "")

CISA_KEV_URL = os.getenv(
    "CISA_KEV_URL",
    "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json",
)

RELEVANCE_THRESHOLD_HIGH = float(os.getenv("RELEVANCE_THRESHOLD_HIGH", "0.75"))
RELEVANCE_THRESHOLD_LOW = float(os.getenv("RELEVANCE_THRESHOLD_LOW", "0.4"))

NOTEBOOKLM_PDF_VALUE_THRESHOLD = int(os.getenv("NOTEBOOKLM_PDF_VALUE_THRESHOLD", "14"))

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
PDF_DIR = os.path.join(DATA_DIR, "academic", "pdf")
NOTEBOOKLM_DIR = os.path.join(DATA_DIR, "notebooklm")
REPORTS_DIR = os.path.join(DATA_DIR, "reports")

# NotebookLM'e giden konu klasörleri: kaynak dokümandaki (bölüm 30) notebook fikriyle
# birebir eşleşir. Analiz agent'ının döndürdüğü primary_domain metni buradaki
# anahtar kelimelerden biriyle eşleşirse ilgili konuya, yoksa "General" a düşer.
NOTEBOOKLM_TOPICS: dict[str, list[str]] = {
    "SOC_SIEM": ["soc", "siem", "security operations", "log analysis", "wazuh", "splunk"],
    "Threat_Intelligence": ["threat intelligence", "threat hunting", "ioc", "cti", "attribution"],
    "Malware_Research": ["malware", "ransomware", "reverse engineering", "botnet"],
    "LLM_Security": ["llm", "large language model", "prompt injection", "ai security", "genai"],
    "Digital_Forensics": ["forensic", "incident response", "dfir"],
    "Network_Security": ["network security", "intrusion detection", "ids", "ips", "anomaly detection"],
    "ICS_OT_Security": ["ics", "scada", "ot security", "industrial control"],
}
