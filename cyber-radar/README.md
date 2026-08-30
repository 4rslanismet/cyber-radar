# Cyber Intelligence Radar — Tek Sunucu Sürümü

Günde 2 kez (varsayılan: 07:30 / 19:30) çalışan, akademik siber güvenlik
makalelerini ve haberleri toplayıp Gemini API ile analiz eden, sonucu
Telegram'a ve NotebookLM'e hazır markdown dosyalarına düşüren basit bir
pipeline.

Bu, orijinal geniş mimarinin (Neo4j, Celery, Redis, OpenSearch, onlarca
agent...) **bilinçli olarak küçültülmüş** hâli — tek Linux sunucuda, tek
Python process'iyle, günde 2 koşuyla çalışacak şekilde tasarlandı.

## Mimari (özet)

```
systemd timer (07:30 / 19:30)
        │
        ▼
run_pipeline.py
   ├── Akademik toplama: OpenAlex, Crossref, arXiv, Semantic Scholar
   ├── Haber toplama: RSS feed'leri + CISA KEV
   ├── Dedup: DOI/arXiv ID/başlık (makale), canonical URL/CVE/başlık (haber)
   ├── İlgililik filtresi: gemini-3.7-flash (ucuz/hızlı)
   ├── Derin analiz: relevant olanlar için güçlü model
   ├── NotebookLM export: konu+ay bazlı markdown dosyaları
   └── Brifing: Telegram + data/reports/*.md
        │
        ▼
   Postgres + pgvector (tüm veri burada)
```

## Kurulum

### 1. Sunucu hazırlığı

```bash
sudo apt update && sudo apt install -y python3-venv python3-pip docker.io docker-compose-plugin
sudo useradd -r -m -d /opt/cyber-radar radar   # opsiyonel: ayrı bir sistem kullanıcısı
```

### 2. Projeyi sunucuya kopyalayın

Bu klasörü `/opt/cyber-radar` altına yerleştirin (scp, git, rsync — tercihiniz).

### 3. Python ortamı

```bash
cd /opt/cyber-radar
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 4. Veritabanı

```bash
docker compose up -d
# şema docker-entrypoint-initdb.d üzerinden otomatik yüklenir; kontrol için:
docker compose exec db psql -U radar -d cyber_radar -c '\dt'
```

### 5. Konfigürasyon

```bash
cp .env.example .env
nano .env
```

Doldurmanız gerekenler:

- `GEMINI_API_KEY` — https://aistudio.google.com/app/apikey
- `CONTACT_EMAIL` — Crossref/Unpaywall "polite pool" için gerçek bir e-posta
- `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` — @BotFather ile bot oluşturup
  botunuzla bir kez konuşun, sonra `https://api.telegram.org/bot<TOKEN>/getUpdates`
  ile `chat.id` değerinizi öğrenin
- `KEYWORDS` — sizi ilgilendiren konular (SOC, threat intel, LLM security vb.)
- `NEWS_FEEDS` — **deploy etmeden önce her feed URL'sini tarayıcıda açıp
  doğrulayın**, siteler zaman zaman adres değiştirir

> **Model adı notu:** `ANALYSIS_MODEL` varsayılan olarak `gemini-3.7-flash`
> bırakıldı ki kutudan çıktığı gibi çalışsın. Google'ın "pro" seri model
> adları sık değişiyor (bir önceki preview zaten kapatıldı). Daha güçlü akıl
> yürütme (research gap, derin analiz) istiyorsanız
> https://ai.google.dev/gemini-api/docs/models sayfasından güncel pro model
> adını kontrol edip `.env` içinde değiştirin.

### 6. İlk manuel test

```bash
source .venv/bin/activate
python3 -m src.run_pipeline
```

İlk koşu `pipeline_state` boş olduğu için son 24 saati tarar. Konsola brifing
metni basılır; hata alırsanız önce `.env` değerlerini, sonra `NEWS_FEEDS`
URL'lerini kontrol edin.

### 7. systemd ile otomatikleştirme

```bash
sudo cp systemd/cyber-radar.service systemd/cyber-radar.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now cyber-radar.timer
systemctl list-timers cyber-radar.timer   # bir sonraki koşuyu doğrulayın
journalctl -u cyber-radar.service -f      # canlı log
```

`cyber-radar.service` içindeki `ExecStart` satırını kendi venv yolunuza göre
düzenlemeyi unutmayın (varsayılan: `/opt/cyber-radar/.venv/bin/python3`).

---

## NotebookLM iş akışı

NotebookLM'in genel kullanıcıya açık bir API'si yok (yalnızca Enterprise/
preview düzeyinde), bu yüzden pipeline **otomatik yükleme yapmaz** — bunun
yerine `data/notebooklm/` altında sizin manuel sürükleyip bırakacağınız,
düzenli dosyalar üretir:

```
data/notebooklm/
  SOC_SIEM/
    2026-08.md          <- Ağustos ayında bu konuda toplanan tüm makaleler
    2026-08_pdfs/        <- Yüksek değerli makalelerin PDF'leri (opsiyonel)
  Threat_Intelligence/
    2026-08.md
  Malware_Research/
    2026-09.md
  ...
```

**Önerilen kullanım:** her konu için NotebookLM'de ayrı bir notebook açın
(örn. "SOC & SIEM Research", "Threat Intelligence Research" — orijinal
mimari dokümanındaki bölüm 30'daki fikirle birebir aynı). Haftada bir, o
haftaki `.md` dosyasını ilgili notebook'a kaynak olarak sürükleyin. Ay
bittiğinde dosya kapanır, yeni ay yeni dosya açar.

Neden makale başına tek dosya değil de ay+konu başına tek dosya? NotebookLM
ücretsiz planda notebook başına ~50 kaynak sınırlıyor. Bu şekilde yılda
12 kaynak/konu harcarsınız — limitin çok altında kalırsınız. Daha fazla
kaynak isterseniz (Plus/Pro/Ultra) sınırlar yükseliyor ama tasarım aynı
kalır, sadece daha sık (haftalık) dosya bölmek isteyebilirsiniz.

Bir makalenin PDF'i de otomatik kopyalanır (aynı ay/konu altında
`_pdfs/` klasörüne) **eğer** açık erişim PDF'i bulunduysa VE
`novelty_score + academic_value_score` toplamı `.env` içindeki
`NOTEBOOKLM_PDF_VALUE_THRESHOLD` eşiğini geçtiyse — her makalenin PDF'ini
kopyalamak kaynak bütçenizi hızla tüketir, bu yüzden sadece gerçekten
değerli olanlar için yapılır.

---

## Dürüst sınırlamalar (deploy etmeden önce bilin)

- **Bu kod bu ortamda ağ erişimi kapalı olduğu için test edilemedi.**
  Syntax kontrolü yapıldı (`python3 -m py_compile`), ama gerçek API
  çağrılarını kendi sunucunuzda doğrulamanız gerekiyor. İlk koşuda
  `journalctl -u cyber-radar.service` ile logları izleyin.
- RSS feed URL'leri ve CISA KEV JSON adresi zamanla değişebilir —
  deploy öncesi tarayıcıda açıp doğrulayın.
- PDF çözümleme yalnızca açık erişim (Unpaywall / arXiv) kaynaklarını
  dener; paywall bypass yapılmaz. IEEE/ACM/Springer gibi kapalı erişim
  makalelerde çoğunlukla yalnızca ABSTRACT_ONLY analiz alırsınız.
- Gemini'nin pro-tier model adları hızlı değişiyor; `.env` içindeki
  `ANALYSIS_MODEL` değerini periyodik olarak kontrol edin.
- Haber dedup'ı (`is_same_event`) basit bir başlık-benzerliği + CVE/URL
  eşleşmesi kullanıyor — mükemmel değil, zaman zaman aynı olayı iki kez
  görebilir ya da farklı iki olayı birleştirebilir. `review_queue` ve
  `news_events.sources` alanlarını göz atarak kalibre edin.

## Sonraki adımlar (isterseniz)

- **CISA KEV için ayrı, saatlik hafif bir timer**: kritik/aktif exploit
  edilen CVE'leri 12 saat beklemeden anlık öğrenmek isterseniz, tek bir
  API çağrısı yapan ayrı bir küçük script + systemd timer eklenebilir.
- **Haftalık/aylık research brief**: `digest.py`'a orijinal mimarideki
  bölüm 27-28 şablonlarını (haftalık akademik/tehdit istihbaratı özeti)
  ekleyebilirsiniz — veri zaten `papers`/`news_events` tablosunda duruyor.
- **Daha fazla haber kaynağı**: `NEWS_FEEDS` listesine ekleme yapmak
  yeterli, kod değişikliği gerekmiyor.
- **Knowledge graph**: şimdilik `papers`/`news_events` tablolarındaki
  CVE/vendor/malware alanları arasında ilişki sorguları SQL ile
  yapılabilir; gerçek ihtiyaç doğarsa Neo4j eklenebilir.
