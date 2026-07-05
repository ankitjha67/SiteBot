# SiteBot

Crawl a client's website, build a knowledge base, and serve a grounded frontend
chatbot that answers visitor questions using only that site's content, with
citations. Plug and play: one command brings up the database, queue, API, and
worker; one command indexes a site; one script tag embeds the widget on any page.

Version 0.2 implements the MVP plus the roadmap's Phase 1 (production
hardening), Phase 2 (product depth), and the core of Phase 3 (platform):
see `docs/ROADMAP.md` for the feature-by-feature status and
`docs/GTM_MONETIZATION.md` for the plan to sell it.

## What it does

1. Crawl. Discovers pages from `sitemap.xml` and same-site links, respects
   `robots.txt`, rate limits, caps page count, and reports failed URLs.
2. Extract. Pulls clean main-body text with trafilatura and dedupes blocks.
3. Diff. Hashes each page and re-embeds only new or changed pages; removed
   pages are pruned (incremental refresh).
4. Chunk and embed. Overlapping windows, embedded via OpenAI or a local model,
   with per-batch retry and all-or-nothing page indexing.
5. Store. Chunks and vectors in Postgres + pgvector, scoped per site.
6. Answer. Blocked-topic check -> canned answers -> answer cache -> grounded
   retrieval with a confidence floor -> streamed, cited Claude answer in the
   visitor's language, with the site's configured tone.
7. Serve. An embeddable `widget.js` (Shadow DOM, SSE) with suggested questions,
   thumbs feedback, lead capture at high-intent moments, human handoff, avatar,
   position, and optional white-label branding.
8. Operate. Admin dashboard, per-site analytics (deflection, top and unanswered
   questions), leads and handoff inboxes, webhooks to Slack/Zapier/anything,
   scheduled re-crawls, quotas, and Stripe billing hooks.

## Architecture

```
Visitor browser                       Admin browser
   |  widget.js (Shadow DOM, SSE)        |  /dashboard (single-file UI)
   v                                     v
FastAPI service ---- /v1/chat/stream ----> retrieve (pgvector) -> Claude (stream)
   |    admin API: tenants, sites, ingest, analytics, leads, billing
   |    enqueues ingest jobs
   v
Redis (arq queue, rate limits) <---- worker: crawl -> diff -> chunk -> embed -> store
   |                                        + cron: scheduled re-crawls
   v
Postgres + pgvector (tenants, sites, pages, chunks, conversations, leads,
                     handoffs, usage, answer cache, migrations)
```

Provider seams are pluggable, no code changes needed:

- **Answer model** (`llm.py`, `ANSWER_PROVIDER`): `anthropic` (Claude, default),
  `openai` (GPT), `gemini` (Google, `pip install ".[gemini]"`), or
  `openai_compatible` — any endpoint speaking the OpenAI protocol, which covers
  Ollama, Groq, Together, Mistral, vLLM, and LM Studio via one base URL, e.g.
  `OPENAI_COMPATIBLE_BASE_URL=http://localhost:11434/v1` + `ANSWER_MODEL=llama3.1`.
- **Embeddings** (`embeddings.py`, `EMBED_PROVIDER`): OpenAI or local
  sentence-transformers.
- **Vector store** (`store.py`): pgvector; the interface is small enough to swap.

Without `REDIS_URL` everything falls back to in-process equivalents for
single-instance development.

## Quickstart

### Option A: Docker (recommended)

```bash
cp .env.example .env
# edit .env: set ANTHROPIC_API_KEY, OPENAI_API_KEY, ADMIN_API_KEY
docker compose up --build     # db + redis + api + worker
```

Create a tenant and a site, then index it:

```bash
# Create a tenant (returns a tk_ API key, shown once)
curl -s -X POST http://localhost:8000/v1/tenants \
  -H "X-API-Key: $ADMIN_API_KEY" -H "Content-Type: application/json" \
  -d '{"name":"Acme","email":"ops@acme.com","plan":"starter"}'

# Create a site with the tenant key (returns a pk_ public key)
curl -s -X POST http://localhost:8000/v1/sites \
  -H "X-API-Key: tk_..." -H "Content-Type: application/json" \
  -d '{"name":"Acme","start_url":"https://www.example.com","display_name":"Acme Assistant"}'

# Kick off crawl + index (runs on the worker)
curl -s -X POST http://localhost:8000/v1/sites/www-example-com/ingest -H "X-API-Key: tk_..."
```

Or skip curl entirely: open `http://localhost:8000/dashboard`, paste your key,
and do all of the above in the UI.

### Option B: Local Python

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
# start a Postgres with pgvector however you like, then:
export DATABASE_URL=postgresql://sitebot:sitebot@localhost:5432/sitebot
export ANTHROPIC_API_KEY=... OPENAI_API_KEY=... ADMIN_API_KEY=...
sitebot init-db
sitebot ingest-url https://www.example.com    # one-shot: create + index, prints public key
sitebot serve
```

Then open `widget/demo.html` with the printed public key, or the dashboard at
`http://localhost:8000/dashboard`.

## CLI

| Command | Purpose |
| --- | --- |
| `sitebot init-db` | Create tables and run migrations |
| `sitebot migrate` | Apply pending SQL migrations |
| `sitebot create-tenant NAME --plan growth` | Create a tenant, print its API key |
| `sitebot ingest-url URL [--full]` | Create + index a site in one step |
| `sitebot recrawl SLUG [--full]` | Re-crawl an existing site |
| `sitebot serve` | Run the API |
| `sitebot worker` | Run the background worker (needs `REDIS_URL`) |

## API summary

| Method | Path | Auth | Purpose |
| --- | --- | --- | --- |
| POST | `/v1/tenants` | admin | Create a tenant, returns its scoped API key |
| POST | `/v1/signup` | public | Self-serve signup (free plan) |
| GET | `/v1/tenants/me` | tenant | Plan, usage, quota |
| POST | `/v1/sites` | admin/tenant | Create a site, returns public key |
| GET | `/v1/sites` | admin/tenant | List sites (row-scoped per tenant) |
| POST | `/v1/sites/{slug}/ingest?full=` | admin/tenant | Start crawl and indexing |
| GET | `/v1/sites/{slug}` | admin/tenant | Status, settings, crawl report |
| PATCH | `/v1/sites/{slug}` | admin/tenant | Update widget/behaviour settings |
| GET | `/v1/sites/{slug}/analytics[...]` | admin/tenant | Summary, top questions, unanswered |
| GET | `/v1/sites/{slug}/conversations[...]` | admin/tenant | Browse transcripts |
| GET | `/v1/sites/{slug}/leads` `/handoffs` | admin/tenant | Captured leads, handoff requests |
| POST | `/v1/billing/checkout` | tenant | Stripe Checkout session |
| POST | `/v1/billing/webhook` | Stripe | Keeps plan/status in sync |
| GET | `/v1/widget/config?key=` | public | Widget theme, features, freshness |
| POST | `/v1/chat/stream` | public | Streaming answer (SSE) |
| POST | `/v1/chat` | public | Non-streaming answer + sources |
| POST | `/v1/feedback` | public | Thumbs up/down on an answer |
| POST | `/v1/leads` | public | Lead capture from the widget |
| POST | `/v1/handoff` | public | Human handoff request |
| GET | `/dashboard` | key in UI | Admin dashboard |
| GET | `/widget.js` | none | The embeddable widget |
| GET | `/healthz` `/readyz` | none | Liveness / readiness (DB check) |

## Embedding the widget on a client site

```html
<script src="https://cdn.yourdomain.com/widget.js"
        data-key="pk_xxx"
        data-api="https://api.yourdomain.com"></script>
```

The widget reads its theme, name, avatar, position, suggested questions, lead
capture, handoff, and branding flags from the server, so you can change any of
it per client from the dashboard without redeploying the snippet.

## Answer quality controls (per site, in the dashboard)

- Canned answers: substring pattern -> fixed response, served without a model call.
- Blocked topics: politely declined, no model call.
- Confidence floor: below it the bot admits it does not know (and the question
  lands in the unanswered report) instead of guessing.
- Tone: one line, e.g. "warm and playful", appended to the system prompt.
- Answer cache: repeat questions are served from Postgres for `ANSWER_CACHE_TTL_S`,
  cutting model spend; invalidated automatically on re-crawl.

## Secrets Guardian (never reveal company secrets)

Enable it per site in the dashboard's **Security** tab. The owner lists literal
secrets (API keys, internal URLs, unpublished prices) and confidential topics
(margins, salaries, unreleased products). The guarantee does **not** depend on
the model obeying a prompt — a prompt instruction alone is defeated by a good
jailbreak. It is defense-in-depth:

1. **Retrieval filter** — any indexed chunk containing a literal secret is
   dropped before the model sees it, so secrets are not in the answer context.
2. **Prompt hardening** — a firm confidentiality directive lists the protected
   *topics* (never the literal values) so the model self-censors.
3. **Deterministic output scan** — the finished answer is scanned for every
   literal secret with obfuscation-resistant normalization (case, spacing,
   punctuation). A hit replaces the whole answer with the refusal message. This
   holds even if the model is fully jailbroken, because it runs on the output,
   not the model's goodwill.
4. **Semantic auditor** (optional LLM) — a strict yes/no classifier catches
   paraphrased or translated topic leaks the literal scan cannot. A detected
   jailbreak attempt forces it on even if the owner left it off.

Literal secrets are used only for scanning and are never sent to any model, so
the guard can never become the leak vector. Guarded answers are never cached.
Guard enforcement applies everywhere the bot answers — widget, playground,
Telegram, Slack, and WhatsApp.

## Knowledge sources

Beyond crawling, index a site's knowledge from uploads and manual entries in the
dashboard's **Knowledge** tab: PDF, DOCX, TXT, MD, CSV, HTML, JSON, and **`.sql`
database dumps** (INSERT rows are converted to readable sentences so the bot can
answer from structured product/order/FAQ data without running the database),
plus raw text snippets and Q&A pairs. Uploaded sources survive a full re-crawl.

## Voice

The widget supports voice with no extra infrastructure: a microphone button
dictates the visitor's question (browser speech-to-text) and a speaker toggle
reads answers aloud (text-to-speech), both localized to the widget language.

## Security and correctness notes

- Only index websites you own or are authorised to index. Make this a term of
  service and a checkbox at signup. The crawler honours `robots.txt`.
- The global admin key is the superuser; each tenant gets a scoped `tk_` key
  (stored as a sha256 hash) that can only see its own sites.
- With `REDIS_URL` set, rate limits are shared across instances; per-plan
  monthly quotas are enforced at request time.
- Per-site `allowed_origins` locks the chat endpoints to the customer's domains;
  global `CORS_ORIGINS` should also be locked down in production.
- The answer prompt treats retrieved content as untrusted data and instructs the
  model to ignore instructions embedded in it, mitigating prompt injection.
- Changing the embedding model changes the vector dimension. Keep `EMBED_DIM`
  and the `vector(N)` columns in `sql/schema.sql` in sync, and run a `--full`
  re-index.
- Schema changes ship as plain SQL files in `sql/migrations/`, applied once each
  and recorded in `schema_migrations`.

## Evaluation harness

```bash
python evals/run_evals.py --slug www-example-com --file evals/example_evals.json
```

Runs question/expectation pairs against the live pipeline and exits non-zero on
regressions; wire it into CI per customer vertical.

## Validation status

Offline validation in this environment: all modules import, ruff passes, and the
unit test suite (crawling, extraction, chunking, hashing, auth keys, quotas,
quality controls, rate limiter) passes. Full end-to-end runs (database writes,
embedding and Claude calls, SSE streaming, worker jobs) require Postgres, Redis,
and API keys, covered by the quickstart above.

## License

MIT. See headers for third-party components.
