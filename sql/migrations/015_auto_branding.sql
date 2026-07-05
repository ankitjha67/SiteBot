-- Auto-branding: the crawler detects the site's font and brand colour and the
-- widget matches them, so the assistant looks native to each client's site.
ALTER TABLE sites ADD COLUMN IF NOT EXISTS widget_font TEXT NOT NULL DEFAULT '';
ALTER TABLE sites ADD COLUMN IF NOT EXISTS widget_font_url TEXT NOT NULL DEFAULT '';
-- Set once on first crawl so re-crawls never overwrite an operator's choices.
ALTER TABLE sites ADD COLUMN IF NOT EXISTS brand_extracted BOOLEAN NOT NULL DEFAULT FALSE;
