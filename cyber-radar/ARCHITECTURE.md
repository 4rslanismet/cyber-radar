# Cyber Intelligence Radar — V0 Mimari ve Konfigürasyon

*Tek Linux sunucu için sadeleştirilmiş sürüm. Bu doküman, orijinal geniş
mimariden (`Cyber_Intelligence_Radar_Genel_Mimari.md`) yola çıkarak kişisel
kullanım için karara bağlanan her şeyin nihai özetidir. Kod teslimatı ayrı
(`cyber-radar.zip`); bu dosya "neden böyle karar verildi" referansıdır.*

---

## 1. Vizyon ve Kapsam Kararı

**Amaç:** Akademik siber güvenlik makalelerini gözden kaçırmamak + günde 2
kez (sabah/akşam) haber ve tehdit istihbaratı özeti almak — tek kişi, tek
Linux sunucu.

**Bilinçli olarak kapsam dışı bırakılanlar** (orijinal mimaride vardı, V0'da
yok):

| Bileşen | Neden çıkarıldı |
|---|---|
| Redis / Celery / Dramatiq | Günde 2 koşu için dağıtık kuyruk gereksiz; systemd timer + tek Python process yeterli |
| Neo4j (Knowledge Graph) | Gerçek ihtiyaç doğmadan eklenmedi; ilişki sorguları şimdilik Postgres üzerinde SQL ile yapılabilir |
| OpenSearch / Elasticsearch | Kişisel ölçekte Postgres full-text + pgvector yeterli |
| MinIO / object storage | PDF'ler yerel diskte (`data/academic/pdf/`) tutuluyor |
| GROBID | Ağır Java servisi; citation graph V0'da hedef değil |
| Playwright / HTML crawling | Sadece resmi API + RSS kullanılıyor, tarayıcı otomasyonu yok |
| 9+ akademik agent, 6+ haber agent | 2 LLM çağrısına indirildi: **ilgililik filtresi** + **derin analiz** |
| Google Scholar entegrasyonu | Resmi API'si yok, scraping riskli; yerine manuel Google Scholar Alerts (opsiyonel, insan-destekli yedek katman) önerildi |

---

## 2. Üst Seviye Akış

```
                    systemd timer (07:30 ve 19:30)
                                │
                                ▼
                        run_pipeline.py
                                │
        ┌───────────────────────┼───────────────────────┐
        ▼                       ▼                       │
  Akademik toplama         Haber toplama                 │
  OpenAlex, Crossref,      RSS feed'leri +               │
  arXiv, Semantic Scholar  CISA KEV                       │
        │                       │                        │
        └───────────┬───────────┘                        │
                     ▼                                    │
                   Dedup                                  │
        (DOI/arXiv ID/başlık)  (canonical URL/CVE/başlık) │
                     │                                    │
                     ▼                                    │
          İlgililik filtresi (Level 1 — ucuz model)       │
           relevant / uncertain / irrelevant              │
                     │                                    │
        uncertain ───┴──► review_queue (asla silinmez)    │
                     │                                    │
                     ▼                                    │
        Derin analiz (Level 3-4 — güçlü model)             │
   makale: PDF varsa tam metin, yoksa ABSTRACT_ONLY         │
   haber: entity extraction + deterministik öncelik skoru   │
                     │                                    │
        ┌────────────┴────────────┐                       │
        ▼                         ▼                       │
  NotebookLM export         Postgres + pgvector            │
  (konu+ay bazlı .md)       (tüm kayıtlar burada)          │
        │                         │                        │
        └────────────┬────────────┘                        │
                     ▼                                     │
              Brifing üret + Telegram'a gönder ◄────────────┘
                     │
                     ▼
            pipeline_state.last_run_at güncelle
```

---

## 3. Teknoloji Yığını (Final)

| Katman | Seçim | Not |
|---|---|---|
| Veritabanı | PostgreSQL + pgvector | `pgvector/pgvector:pg16` Docker imajı |
| Orkestrasyon | Python 3 + systemd timer | Redis/Celery yok |
| HTTP | httpx | retry için tenacity ile sarılı |
| RSS | feedparser | |
| PDF metin çıkarma | PyMuPDF (fitz) | yalnızca açık erişim PDF'lerde |
| LLM | **Gemini API** (`google-genai` SDK) | eski `google-generativeai` artık desteklenmiyor |
| Bildirim | Telegram Bot API | tek HTTP isteği, SMTP derdi yok |
| Altyapı | Docker Compose | yalnızca Postgres konteyneri |
| Kişisel araştırma katmanı | NotebookLM (manuel) | API'si olmadığı için otomasyona dahil edilmedi |

---

## 4. Veri Kaynakları

### Akademik (4 kaynak, paralel sorgulanır — "kaçırmamak" için tek kaynağa güvenilmez)

| Kaynak | Yöntem | Not |
|---|---|---|
| OpenAlex | REST API (`api.openalex.org/works`) | `mailto` ile polite pool |
| Crossref | REST API (`api.crossref.org/works`) | `User-Agent: mailto:` header |
| arXiv | Atom API (`export.arxiv.org/api/query`) | `cat:cs.CR` filtresiyle |
| Semantic Scholar | Graph API | opsiyonel API key, yoksa da çalışır (düşük rate limit) |

**PDF çözümleme sırası:** Unpaywall (DOI varsa) → arXiv PDF linki. Paywall
bypass yapılmaz; bulunamazsa `analysis_type = ABSTRACT_ONLY`.

### Haber

- RSS feed listesi (`.env` → `NEWS_FEEDS`, kolayca genişletilebilir)
- CISA KEV JSON listesi (aktif exploit edilen CVE'ler → öncelik skoruna girdi)

### Bilinçli olarak V0 dışında bırakılan yedek katman

- **Google Scholar Alerts** (e-posta tabanlı, manuel): scraping yapılmıyor,
  ama isterseniz Scholar'dan gelen e-posta bildirimlerini kendiniz gözden
  geçirerek sistemin kaçırdığı makaleleri yakalayabilirsiniz. Otomasyona
  dahil edilmedi çünkü resmi API yok.

---

## 5. Zamanlama

| Ayar | Değer | Gerekçe |
|---|---|---|
| Koşu sıklığı | Günde 2 (07:30 / 19:30) | Akademik yayın hızı haber kadar yüksek değil; günde birkaç kez toplama fazlasıyla yeterli |
| Pencere mantığı | `pipeline_state.last_run_at` | İki koşu arasında hiçbir şey çift sayılmaz, hiçbir şey atlanmaz |
| İlk koşu davranışı | Son 24 saat | `last_run_at` boşsa varsayılan pencere |
| `RandomizedDelaySec` | 300 sn | Timer'ın tam saniyesinde değil, birkaç dakika içinde tetiklenmesi (sunucu yükünü dağıtmak için) |

**Bilinçli olarak eklenmeyen:** CISA KEV için ayrı, saatlik hafif bir timer.
En kötü ihtimalle kritik bir CVE'yi 12 saat sonra öğrenirsiniz — kişisel
takip için kabul edilebilir bir bedel. İsterseniz sonradan tek bir API
çağrısı yapan ayrı bir mini-script + timer olarak eklenebilir (bkz. §16).

---

## 6. "Makale Kaçırmama" Stratejisi

1. **Çoklu kaynak paralel sorgu** — OpenAlex, Crossref, arXiv, Semantic
   Scholar aynı anahtar kelime setiyle sorgulanır; biri kaçırırsa diğeri
   yakalar. Dedup DOI/arXiv ID/normalize başlık üzerinden yapılır.
2. **Belirsiz olan asla silinmez** — İlgililik filtresi düşük güvenle
   sınıflandırırsa kayıt `review_queue`'ya düşer, otomatik atılmaz.
3. **Coverage audit** — Her koşu, bir önceki koşuyla toplam sonuç sayısını
   karşılaştırır (`_coverage_warning`). Bu koşu öncekinin %30'undan azını
   getirdiyse brifingin başına uyarı eklenir ("bir kaynak/feed bozulmuş
   olabilir").
4. **`collector_runs` tablosu** — Her toplama koşusu (kaynak, sorgu, sonuç
   sayısı, hata) loglanır; sessiz başarısızlık olmaz.
5. **arXiv gerçek zamanlıya yakın** — arXiv preprint gecikmesi diğer
   kaynaklara göre en düşük; en hızlı sinyal genelde buradan gelir.
6. **(Opsiyonel, manuel) Google Scholar Alerts** — İsterseniz insan-destekli
   yedek katman olarak devreye alabilirsiniz (bkz. §4).

**Henüz eklenmeyen ama planlanan:** Anahtar kelime listesinin otomatik
genişletilmesi (toplanan başlık/abstract'lardan yeni terim adayı çıkarma —
orijinal mimarideki "Discovery Agent"ın hafif versiyonu). V0'da `KEYWORDS`
manuel yönetiliyor.

---

## 7. LLM Katmanı ve Model Routing

| Seviye | Kullanım | Model (`.env` değişkeni) | Varsayılan |
|---|---|---|---|
| Level 1 | İlgililik filtresi (makale + haber) | `RELEVANCE_MODEL` | `gemini-3.7-flash` |
| Level 3-4 | Derin analiz (Paper Analyst + Research Agent birleşik; News Analyst) | `ANALYSIS_MODEL` | `gemini-3.7-flash` |

- SDK: `google-genai` (yeni birleşik SDK), `from google import genai`
- Yapılandırılmış çıktı: `response_mime_type="application/json"` — kod
  fence temizlemekten çok daha güvenilir
- Öncelik skoru **LLM'e bırakılmadı** — deterministik Python fonksiyonu
  (bkz. §10), tasarım ilkesiyle tutarlı: "muhakeme gerektirmeyen işler
  klasik servislere bırakılır"

**Bilinen risk:** Google'ın pro-tier model adları hızlı değişiyor (bir
önceki preview sürümü zaten kapatıldı). `ANALYSIS_MODEL` varsayılan olarak
bilinçli şekilde flash bırakıldı ki kutudan çıktığı gibi çalışsın; daha
güçlü akıl yürütme isteniyorsa güncel pro model adı
`https://ai.google.dev/gemini-api/docs/models` sayfasından teyit edilip
`.env` içinde değiştirilmeli.

---

## 8. Veritabanı Şeması (özet)

| Tablo | Amaç |
|---|---|
| `pipeline_state` | `last_run_at` gibi anahtar-değer durumları |
| `collector_runs` | Her toplama koşusunun denetim izi (coverage audit için) |
| `papers` | Akademik makaleler — DOI/arXiv ID/OpenAlex ID/başlık dedup, ilgililik, analiz, NotebookLM konu etiketi |
| `news_events` | Haber olayları — aynı olayın farklı kaynaklardaki haberleri tek satırda (`sources` jsonb dizisi) |
| `review_queue` | Belirsiz sınıflandırılan makale/haberler — çözülene kadar burada bekler |
| `notebooklm_export_log` | Şemada tanımlı, gelecekte daha ince taneli export takibi için ayrılmış; **V0'da doldurulmuyor** — şu an export durumu `papers.notebooklm_topic` kolonuyla takip ediliyor |

`papers` tablosunda `embedding vector(1536)` kolonu var ama V0'da
doldurulmuyor — ileride "benzer makale" araması eklemek isterseniz hazır.

---

## 9. Dedup Mantığı

| Alan | Sinyaller |
|---|---|
| Akademik | DOI → arXiv ID → OpenAlex ID → normalize edilmiş başlık (bu sırayla kontrol edilir) |
| Haber | Canonical URL (tracking parametreleri temizlenmiş) VEYA CVE kesişimi VEYA başlık benzerliği (%72 eşik, `SequenceMatcher`) — 14 günlük pencere içinde |

Haber tarafında eşleşme bulunursa yeni satır açılmaz, mevcut olayın
`sources` listesine kaynak eklenir ("aynı olayın 20 haberi = 1 event, 20
source" prensibi).

---

## 10. Öncelik Skoru (Haberler — Deterministik)

| Faktör | Puan |
|---|---|
| CISA KEV listesinde | +30 |
| Aktif exploitation | +25 |
| Zero-day | +20 |
| Remote code execution | +15 |
| Authentication bypass | +15 |
| Ransomware kullanımı | +15 |
| Internet-facing ürün | +10 |
| Kritik altyapı etkisi | +10 |

Skor eşikleri: `≥80` CRITICAL, `≥55` HIGH, `≥30` MEDIUM, altı LOW.

---

## 11. NotebookLM Entegrasyonu

**Karar:** NotebookLM'in genel kullanıcıya açık API'si yok (yalnızca
Enterprise/preview düzeyinde; gayri-resmi çerez-tabanlı scraper'lar hesap
riski taşıyor). Bu yüzden pipeline **otomatik yükleme yapmaz** — konuya ve
aya göre gruplanmış, elle sürükleyip bırakılacak markdown dosyaları üretir.

**Neden makale başına dosya değil, konu+ay başına dosya:** NotebookLM
ücretsiz planda notebook başına ~50 kaynak sınırlıyor. Bu yapıyla yılda
12 kaynak/konu harcanır — limitin çok altında.

**Konu haritası** (`config.NOTEBOOKLM_TOPICS` — analiz agent'ının döndürdüğü
`primary_domain` bu anahtar kelimelerle eşleştirilir, eşleşme yoksa
`General_Cybersecurity`'ye düşer):

| Konu klasörü | Anahtar kelimeler |
|---|---|
| `SOC_SIEM` | soc, siem, security operations, log analysis, wazuh, splunk |
| `Threat_Intelligence` | threat intelligence, threat hunting, ioc, cti, attribution |
| `Malware_Research` | malware, ransomware, reverse engineering, botnet |
| `LLM_Security` | llm, large language model, prompt injection, ai security, genai |
| `Digital_Forensics` | forensic, incident response, dfir |
| `Network_Security` | network security, intrusion detection, ids, ips, anomaly detection |
| `ICS_OT_Security` | ics, scada, ot security, industrial control |

**PDF ek kopyalama:** Bir makalenin açık erişim PDF'i varsa VE
`novelty_score + academic_value_score ≥ NOTEBOOKLM_PDF_VALUE_THRESHOLD`
(varsayılan 14/20) ise, PDF de aynı ay/konu altında `_pdfs/` klasörüne
kopyalanır — her makalenin PDF'i değil, sadece değerli olanlar (kaynak
bütçesini korumak için).

**Kullanım önerisi:** Her konu için ayrı bir NotebookLM notebook'u açın,
haftada bir o ayın dosyasını ilgili notebook'a sürükleyin.

---

## 12. Bildirim

- Telegram Bot API, 4096 karakter limiti için otomatik parçalama
- Brifing içeriği: Kritik/yüksek öncelikli olaylar → diğer haberler → yeni
  akademik makaleler → NotebookLM'de güncellenen dosyalar → review queue
  sayısı → (varsa) coverage audit uyarısı
- Her brifing ayrıca `data/reports/{tarih}_{sabah|aksam}.md` olarak diske
  yazılır (Telegram gitmese bile kayıt kaybolmaz)

---

## 13. Konfigürasyon Referansı (`.env`)

| Değişken | Varsayılan | Açıklama |
|---|---|---|
| `DATABASE_URL` | `postgresql://radar:radar@localhost:5432/cyber_radar` | Postgres bağlantısı |
| `GEMINI_API_KEY` | — | https://aistudio.google.com/app/apikey |
| `RELEVANCE_MODEL` | `gemini-3.7-flash` | Level 1, ucuz/hızlı |
| `ANALYSIS_MODEL` | `gemini-3.7-flash` | Level 3-4, derin analiz — güncel pro modelle değiştirilebilir |
| `CONTACT_EMAIL` | — | Crossref/Unpaywall polite pool için |
| `SEMANTIC_SCHOLAR_API_KEY` | boş (opsiyonel) | Yoksa da çalışır, rate limit düşük olur |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` | — | @BotFather üzerinden |
| `KEYWORDS` | örnek liste | Akademik + haber ortak arama terimleri |
| `NEWS_FEEDS` | örnek liste | RSS URL'leri — deploy öncesi doğrulanmalı |
| `CISA_KEV_URL` | `cisa.gov/.../known_exploited_vulnerabilities.json` | Aktif exploit listesi |
| `RELEVANCE_THRESHOLD_HIGH` | `0.75` | Bu güvenin üzeri → relevant/irrelevant kesinleşir |
| `RELEVANCE_THRESHOLD_LOW` | `0.4` | Bu aralık → uncertain |
| `NOTEBOOKLM_PDF_VALUE_THRESHOLD` | `14` (0-20 arası) | PDF'in de kopyalanması için eşik |

---

## 14. Zamanlama Dosyaları (systemd)

| Dosya | İçerik |
|---|---|
| `systemd/cyber-radar.timer` | `OnCalendar=*-*-* 07:30:00` ve `19:30:00`, `Persistent=true`, `RandomizedDelaySec=300` |
| `systemd/cyber-radar.service` | `Type=oneshot`, `ExecStart=.venv/bin/python3 -m src.run_pipeline`, `WorkingDirectory=/opt/cyber-radar` |

---

## 15. Proje Klasör Yapısı

```
cyber-radar/
├── docker-compose.yml          # yalnızca Postgres+pgvector
├── .env.example
├── requirements.txt
├── db/schema.sql
├── src/
│   ├── config.py                # .env okuyucu, NOTEBOOKLM_TOPICS haritası
│   ├── db.py                    # psycopg3 bağlantı yardımcıları
│   ├── dedup.py                 # başlık/URL normalizasyonu, event eşleştirme
│   ├── collectors/
│   │   ├── academic.py          # OpenAlex, Crossref, arXiv, S2, PDF resolve
│   │   └── news.py              # RSS + CISA KEV
│   ├── llm/
│   │   ├── client.py            # Gemini çağrı sarmalayıcı (JSON çıktı)
│   │   ├── relevance.py         # Level 1
│   │   ├── paper_analyst.py     # Level 3-4 (makale)
│   │   └── news_analyst.py      # Level 3-4 (haber) + deterministik skor
│   ├── notebooklm_export.py     # konu+ay bazlı markdown export
│   ├── digest.py                # brifing üretici
│   ├── notify.py                # Telegram gönderici
│   └── run_pipeline.py          # orkestrasyon (giriş noktası)
├── systemd/
│   ├── cyber-radar.service
│   └── cyber-radar.timer
└── data/                        # git'e girmez (.gitignore)
    ├── academic/pdf/
    ├── notebooklm/{konu}/{yıl-ay}.md
    └── reports/{tarih}_{sabah|aksam}.md
```

---

## 16. Dürüst Sınırlamalar

- Bu kod, geliştirme ortamında ağ erişimi kapalı olduğu için gerçek API
  çağrılarıyla test edilemedi — yalnızca syntax kontrolü yapıldı
  (`python3 -m py_compile`). İlk deploy'da `journalctl -u cyber-radar.service`
  ile izlenmesi önerilir.
- RSS feed URL'leri ve CISA KEV JSON adresi zamanla değişebilir.
- PDF çözümleme yalnızca açık erişim kaynaklarını dener; paywall'lı
  yayınlarda (IEEE, ACM, Springer vb.) çoğunlukla ABSTRACT_ONLY analiz
  alırsınız.
- Haber dedup'ı basit bir başlık-benzerliği + CVE/URL eşleşmesi kullanır;
  mükemmel değildir — zaman zaman kalibrasyon (`review_queue`, `sources`
  alanı gözden geçirilerek) gerekebilir.
- `notebooklm_export_log` tablosu şemada var ama V0 kodunda doldurulmuyor
  (export durumu `papers.notebooklm_topic` ile takip ediliyor) — ileride
  daha ince taneli takip gerekirse kullanılabilir.

---

## 17. Planlanan Ama V0'a Dahil Edilmeyen Genişletmeler

| Fikir | Ne zaman gerekir |
|---|---|
| CISA KEV için ayrı saatlik hafif timer | 12 saatlik gecikme kabul edilemez hale gelirse |
| Otomatik anahtar kelime genişletme (Discovery Agent) | `KEYWORDS` listesini elle güncellemek yorucu hale gelirse |
| Haftalık/aylık research brief (`digest.py` genişletmesi) | Günlük özetler yetersiz kalırsa — veri zaten tabloda duruyor |
| Neo4j / Knowledge Graph | CVE-aktör-makale ilişki sorguları SQL ile karmaşıklaşırsa |
| Google Scholar Alerts entegrasyonu (manuel) | Coverage audit sürekli düşük kalıyor ve kaynak eksikliği şüphesi varsa |

---

*Kod teslimatı: `cyber-radar.zip`. Kurulum adımları için zip içindeki
`README.md`'ye bakın.*
