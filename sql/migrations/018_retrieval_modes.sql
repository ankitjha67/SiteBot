-- Retrieval + answer modes per site.
--   retrieval_mode: hybrid (default) | agentic (iterative retrieve-refine)
--   answer_mode:    llm (default) | extractive (no LLM call = zero token cost)
--   fallback_extractive: if the LLM errors/quota-exhausts, answer extractively
--     instead of showing an error.
ALTER TABLE sites ADD COLUMN IF NOT EXISTS retrieval_mode TEXT NOT NULL DEFAULT 'hybrid';
ALTER TABLE sites ADD COLUMN IF NOT EXISTS answer_mode TEXT NOT NULL DEFAULT 'llm';
ALTER TABLE sites ADD COLUMN IF NOT EXISTS fallback_extractive BOOLEAN NOT NULL DEFAULT TRUE;
