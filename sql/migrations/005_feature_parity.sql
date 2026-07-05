-- Batch A feature parity: conversation memory, knowledge sources, per-site
-- model override, custom instructions, retention, proactive teaser, inbox.

-- Per-site AI behaviour.
ALTER TABLE sites ADD COLUMN IF NOT EXISTS custom_instructions TEXT NOT NULL DEFAULT '';
ALTER TABLE sites ADD COLUMN IF NOT EXISTS model_provider TEXT NOT NULL DEFAULT '';  -- '' = server default
ALTER TABLE sites ADD COLUMN IF NOT EXISTS model_name TEXT NOT NULL DEFAULT '';      -- '' = server default
ALTER TABLE sites ADD COLUMN IF NOT EXISTS history_turns INT NOT NULL DEFAULT 6;

-- GDPR-style retention. 0 keeps conversations forever.
ALTER TABLE sites ADD COLUMN IF NOT EXISTS retention_days INT NOT NULL DEFAULT 0;

-- Proactive engagement teaser shown by the widget after a delay. 0 disables.
ALTER TABLE sites ADD COLUMN IF NOT EXISTS proactive_message TEXT NOT NULL DEFAULT '';
ALTER TABLE sites ADD COLUMN IF NOT EXISTS proactive_delay_s INT NOT NULL DEFAULT 0;

-- Knowledge sources beyond the crawler: uploaded files, raw text, Q&A pairs.
-- Chunks for a source use chunks.url = sources.ref (a source:// pseudo-URL),
-- which keeps retrieval, citations, and deletion uniform with crawled pages.
CREATE TABLE IF NOT EXISTS sources (
    id           BIGSERIAL PRIMARY KEY,
    site_id      BIGINT NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
    kind         TEXT NOT NULL,             -- file | text | qa
    title        TEXT NOT NULL DEFAULT '',
    ref          TEXT NOT NULL UNIQUE,      -- source://<token>, used as chunks.url
    chars        INT NOT NULL DEFAULT 0,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_sources_site ON sources(site_id);
