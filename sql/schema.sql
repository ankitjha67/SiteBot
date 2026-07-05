-- SiteBot schema. Requires the pgvector extension.
-- The vector dimension below (1536) matches OpenAI text-embedding-3-small.
-- If you change the embedding model, change every vector(1536) to the new dim
-- and set EMBED_DIM in the environment to match.

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- A tenant is a paying customer account.
CREATE TABLE IF NOT EXISTS tenants (
    id           BIGSERIAL PRIMARY KEY,
    name         TEXT NOT NULL,
    plan         TEXT NOT NULL DEFAULT 'trial',
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- A site is one website knowledge base belonging to a tenant.
CREATE TABLE IF NOT EXISTS sites (
    id                BIGSERIAL PRIMARY KEY,
    tenant_id         BIGINT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    slug              TEXT NOT NULL UNIQUE,        -- public identifier used by the widget
    start_url         TEXT NOT NULL,
    public_key        TEXT NOT NULL UNIQUE,        -- widget key, safe to expose in HTML
    display_name      TEXT NOT NULL DEFAULT 'Assistant',
    theme_color       TEXT NOT NULL DEFAULT '#4f46e5',
    welcome_message   TEXT NOT NULL DEFAULT 'Hi. Ask me anything about this site.',
    status            TEXT NOT NULL DEFAULT 'new', -- new | crawling | indexing | ready | error
    last_error        TEXT,
    pages_indexed     INT NOT NULL DEFAULT 0,
    chunks_indexed    INT NOT NULL DEFAULT 0,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_sites_tenant ON sites(tenant_id);

-- One row per indexed content chunk.
CREATE TABLE IF NOT EXISTS chunks (
    id            BIGSERIAL PRIMARY KEY,
    site_id       BIGINT NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
    url           TEXT NOT NULL,
    title         TEXT NOT NULL DEFAULT '',
    content       TEXT NOT NULL,
    token_count   INT NOT NULL DEFAULT 0,
    embedding     vector(1536) NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_chunks_site ON chunks(site_id);
-- Approximate nearest neighbour index for cosine distance.
-- HNSW gives good recall and speed. Build after a bulk load for large sites.
CREATE INDEX IF NOT EXISTS idx_chunks_embedding
    ON chunks USING hnsw (embedding vector_cosine_ops);
-- Trigram index supports keyword fallback search.
CREATE INDEX IF NOT EXISTS idx_chunks_content_trgm
    ON chunks USING gin (content gin_trgm_ops);

-- Conversations and messages, for history and analytics.
CREATE TABLE IF NOT EXISTS conversations (
    id           BIGSERIAL PRIMARY KEY,
    site_id      BIGINT NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
    visitor_id   TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS messages (
    id                BIGSERIAL PRIMARY KEY,
    conversation_id   BIGINT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role              TEXT NOT NULL,   -- user | assistant
    content           TEXT NOT NULL,
    sources           JSONB NOT NULL DEFAULT '[]',
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(conversation_id);

-- Usage events power metering and billing.
CREATE TABLE IF NOT EXISTS usage_events (
    id           BIGSERIAL PRIMARY KEY,
    tenant_id    BIGINT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    site_id      BIGINT NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
    kind         TEXT NOT NULL,   -- message | ingest_page
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Quota queries filter on created_at >= date_trunc('month', now()), which a
-- plain btree serves. (date_trunc on timestamptz is not IMMUTABLE, so it
-- cannot appear in an index expression.)
CREATE INDEX IF NOT EXISTS idx_usage_tenant_created
    ON usage_events(tenant_id, created_at);
