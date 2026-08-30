-- Cyber Intelligence Radar - basit tek-sunucu şeması
-- pgvector extension'ı embedding kolonu için gerekli (opsiyonel kullanım, ileride
-- "benzer makale / benzer olay" aramaları için).

CREATE EXTENSION IF NOT EXISTS vector;

-- ---------------------------------------------------------------------------
-- Pipeline durumu: her koşunun ne zaman çalıştığını tutar (zaman penceresi bunun
-- üzerinden hesaplanır -> hiçbir şey çift işlenmez, hiçbir şey atlanmaz)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS pipeline_state (
    key         text PRIMARY KEY,
    value       text,
    updated_at  timestamptz NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- Her toplama/analiz koşusunun denetim izi (coverage audit için)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS collector_runs (
    id            bigserial PRIMARY KEY,
    source        text NOT NULL,           -- 'openalex' | 'crossref' | 'arxiv' | ... | 'bleepingcomputer'
    kind          text NOT NULL,           -- 'academic' | 'news'
    started_at    timestamptz NOT NULL DEFAULT now(),
    finished_at   timestamptz,
    query         text,
    result_count  integer,
    error         text
);

-- ---------------------------------------------------------------------------
-- Akademik makaleler
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS papers (
    id                  bigserial PRIMARY KEY,
    doi                 text UNIQUE,
    arxiv_id            text UNIQUE,
    openalex_id         text UNIQUE,
    title               text NOT NULL,
    normalized_title    text NOT NULL,
    authors             jsonb NOT NULL DEFAULT '[]',
    venue               text,
    publication_date    date,
    abstract            text,
    pdf_url             text,
    pdf_local_path       text,
    pdf_source          text,             -- 'unpaywall' | 'arxiv' | null
    analysis_type       text NOT NULL DEFAULT 'ABSTRACT_ONLY',  -- ABSTRACT_ONLY | FULL_TEXT
    source_apis         text[] NOT NULL DEFAULT '{}',
    relevance           jsonb,
    relevance_status    text NOT NULL DEFAULT 'pending', -- pending|relevant|uncertain|irrelevant
    analysis            jsonb,
    analyzed_at         timestamptz,
    notebooklm_topic    text,
    embedding           vector(1536),
    created_at          timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_papers_normalized_title ON papers (normalized_title);
CREATE INDEX IF NOT EXISTS idx_papers_relevance_status ON papers (relevance_status);

-- ---------------------------------------------------------------------------
-- Haber / olay kayıtları (aynı olayın farklı kaynaklardaki haberleri tek satırda birleşir)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS news_events (
    id                bigserial PRIMARY KEY,
    title             text NOT NULL,
    dedup_key         text,                 -- normalize edilmiş başlık + öne çıkan CVE
    summary           text,
    sources           jsonb NOT NULL DEFAULT '[]',  -- [{"name":"BleepingComputer","url":"..."}]
    first_seen_at     timestamptz NOT NULL DEFAULT now(),
    last_updated_at   timestamptz NOT NULL DEFAULT now(),
    published_at      timestamptz,
    raw_text          text,
    cves              text[] NOT NULL DEFAULT '{}',
    vendors           text[] NOT NULL DEFAULT '{}',
    products          text[] NOT NULL DEFAULT '{}',
    relevance         jsonb,
    relevance_status  text NOT NULL DEFAULT 'pending',
    analysis          jsonb,
    analyzed_at       timestamptz,
    cisa_kev          boolean NOT NULL DEFAULT false,
    priority_score    integer,
    priority_label    text,
    created_at        timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_news_dedup_key ON news_events (dedup_key);
CREATE INDEX IF NOT EXISTS idx_news_relevance_status ON news_events (relevance_status);
CREATE INDEX IF NOT EXISTS idx_news_cves ON news_events USING gin (cves);

-- ---------------------------------------------------------------------------
-- Düşük güvenli / belirsiz sınıflandırmalar buraya düşer, otomatik silinmez
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS review_queue (
    id          bigserial PRIMARY KEY,
    item_type   text NOT NULL,   -- 'paper' | 'news'
    item_id     bigint NOT NULL,
    reason      text,
    confidence  real,
    created_at  timestamptz NOT NULL DEFAULT now(),
    resolved    boolean NOT NULL DEFAULT false
);

-- ---------------------------------------------------------------------------
-- NotebookLM'e hangi makalenin hangi aylık/konu dosyasına yazıldığının kaydı
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS notebooklm_export_log (
    id          bigserial PRIMARY KEY,
    topic       text NOT NULL,
    period      text NOT NULL,     -- '2026-08'
    file_path   text NOT NULL,
    paper_ids   bigint[] NOT NULL DEFAULT '{}',
    updated_at  timestamptz NOT NULL DEFAULT now(),
    UNIQUE (topic, period)
);
