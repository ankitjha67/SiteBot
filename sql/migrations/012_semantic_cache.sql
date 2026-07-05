-- Semantic answer cache: store the question embedding so differently-phrased
-- duplicates ("price of starter plan?" vs "how much is starter?") can hit the
-- cache. Untyped vector accepts whatever EMBED_DIM the deployment uses; the
-- table stays small (TTL'd, per-site), so a sequential scan is fine.
ALTER TABLE answer_cache ADD COLUMN IF NOT EXISTS question_embedding vector;
