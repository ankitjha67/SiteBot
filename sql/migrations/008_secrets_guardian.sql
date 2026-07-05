-- Secrets Guardian: owner-defined confidential content the bot must NEVER
-- reveal, enforced by defense-in-depth (retrieval filter + deterministic
-- output scan + optional LLM auditor), independent of the model's compliance.

ALTER TABLE sites ADD COLUMN IF NOT EXISTS guard_enabled BOOLEAN NOT NULL DEFAULT FALSE;

-- Literal secret strings (API keys, internal URLs, unpublished prices...).
-- Used ONLY for deterministic scanning; never placed into any model prompt.
ALTER TABLE sites ADD COLUMN IF NOT EXISTS protected_secrets JSONB NOT NULL DEFAULT '[]';

-- Natural-language descriptions of confidential topics ("profit margins",
-- "employee salaries"). Fed to the prompt and the semantic auditor.
ALTER TABLE sites ADD COLUMN IF NOT EXISTS protected_topics JSONB NOT NULL DEFAULT '[]';

-- Run the LLM semantic auditor on each answer (catches paraphrase / translation
-- leaks the literal scanner misses). The literal scan always runs when enabled.
ALTER TABLE sites ADD COLUMN IF NOT EXISTS guard_llm_audit BOOLEAN NOT NULL DEFAULT TRUE;

ALTER TABLE sites ADD COLUMN IF NOT EXISTS guard_refusal_message TEXT NOT NULL DEFAULT
    'I''m sorry, but I can''t share that information.';

-- Count of blocked leak/jailbreak attempts, for the dashboard security panel.
ALTER TABLE sites ADD COLUMN IF NOT EXISTS guard_blocks INT NOT NULL DEFAULT 0;
