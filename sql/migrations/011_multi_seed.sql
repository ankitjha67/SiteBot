-- One client bot can crawl several websites into a single knowledge base.
-- start_url stays the primary seed; extra_urls holds additional seed URLs
-- (each crawled within its own domain scope, all merged into this site).
ALTER TABLE sites ADD COLUMN IF NOT EXISTS extra_urls JSONB NOT NULL DEFAULT '[]';
