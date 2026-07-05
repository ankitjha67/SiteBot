-- Phase 2: product depth.
-- Analytics fields, leads, handoffs, widget customization, answer quality controls.

-- Message-level analytics: whether the bot could answer, retrieval confidence,
-- and visitor feedback (1 = helpful, -1 = not helpful).
ALTER TABLE messages ADD COLUMN IF NOT EXISTS answered BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE messages ADD COLUMN IF NOT EXISTS confidence REAL;
ALTER TABLE messages ADD COLUMN IF NOT EXISTS feedback SMALLINT;

-- Captured leads (email plus free-form note), delivered to a webhook if set.
CREATE TABLE IF NOT EXISTS leads (
    id                BIGSERIAL PRIMARY KEY,
    site_id           BIGINT NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
    conversation_id   BIGINT REFERENCES conversations(id) ON DELETE SET NULL,
    email             TEXT NOT NULL,
    name              TEXT NOT NULL DEFAULT '',
    note              TEXT NOT NULL DEFAULT '',
    visitor_id        TEXT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_leads_site ON leads(site_id);

-- Human handoff requests raised from the widget.
CREATE TABLE IF NOT EXISTS handoffs (
    id                BIGSERIAL PRIMARY KEY,
    site_id           BIGINT NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
    conversation_id   BIGINT REFERENCES conversations(id) ON DELETE SET NULL,
    email             TEXT NOT NULL DEFAULT '',
    message           TEXT NOT NULL DEFAULT '',
    visitor_id        TEXT,
    status            TEXT NOT NULL DEFAULT 'open',  -- open | resolved
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_handoffs_site ON handoffs(site_id);

-- Widget customization and behaviour controls, all per site.
ALTER TABLE sites ADD COLUMN IF NOT EXISTS avatar_url TEXT NOT NULL DEFAULT '';
ALTER TABLE sites ADD COLUMN IF NOT EXISTS widget_position TEXT NOT NULL DEFAULT 'right';
ALTER TABLE sites ADD COLUMN IF NOT EXISTS suggested_questions JSONB NOT NULL DEFAULT '[]';
ALTER TABLE sites ADD COLUMN IF NOT EXISTS lead_capture_enabled BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE sites ADD COLUMN IF NOT EXISTS lead_prompt TEXT NOT NULL DEFAULT
    'Leave your email and we will get back to you.';
ALTER TABLE sites ADD COLUMN IF NOT EXISTS lead_webhook_url TEXT NOT NULL DEFAULT '';
ALTER TABLE sites ADD COLUMN IF NOT EXISTS handoff_enabled BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE sites ADD COLUMN IF NOT EXISTS handoff_webhook_url TEXT NOT NULL DEFAULT '';

-- Answer quality controls.
-- canned_answers: [{"pattern": "refund", "answer": "..."}]  substring match, case-insensitive.
-- blocked_topics: ["politics", ...]                          declined politely.
ALTER TABLE sites ADD COLUMN IF NOT EXISTS canned_answers JSONB NOT NULL DEFAULT '[]';
ALTER TABLE sites ADD COLUMN IF NOT EXISTS blocked_topics JSONB NOT NULL DEFAULT '[]';
ALTER TABLE sites ADD COLUMN IF NOT EXISTS tone TEXT NOT NULL DEFAULT '';
ALTER TABLE sites ADD COLUMN IF NOT EXISTS min_confidence REAL NOT NULL DEFAULT 0.0;
