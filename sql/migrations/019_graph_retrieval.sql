-- Entity graph for multi-hop retrieval. Entities are extracted from chunk text
-- at index time; entity_mentions links each entity to the chunks it appears in.
-- Two entities are "connected" when they co-occur in the same chunk, which lets
-- a query about one entity pull in facts about connected entities (1-hop).
CREATE TABLE IF NOT EXISTS entities (
    id       BIGSERIAL PRIMARY KEY,
    site_id  BIGINT NOT NULL,
    name     TEXT NOT NULL,          -- normalized (lowercase) surface form
    display  TEXT NOT NULL DEFAULT '' -- original casing for readability
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_entities_site_name ON entities (site_id, name);

CREATE TABLE IF NOT EXISTS entity_mentions (
    entity_id BIGINT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    chunk_id  BIGINT NOT NULL REFERENCES chunks(id) ON DELETE CASCADE,
    site_id   BIGINT NOT NULL,
    PRIMARY KEY (entity_id, chunk_id)
);
CREATE INDEX IF NOT EXISTS idx_mentions_chunk ON entity_mentions (chunk_id);
CREATE INDEX IF NOT EXISTS idx_mentions_site ON entity_mentions (site_id);
