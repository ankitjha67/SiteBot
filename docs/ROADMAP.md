# Product Roadmap

From working MVP to a sellable, scalable product. Phases are ordered by what
unblocks revenue first. Timeline assumes a solo builder or a small team working
part time; compress if full time.

## Status as of v0.2

Shipped in this repo:

- Phase 1, all items: arq/Redis job queue with BackgroundTasks dev fallback,
  Redis-backed rate limiting plus per-plan monthly quotas, per-tenant hashed
  API keys with row scoping, JSON logs with request ids and optional Sentry,
  per-batch embedding retry with a failed-URL crawl report, incremental
  re-crawl via per-URL content hashes plus a cron scheduler, `/readyz`,
  per-site `allowed_origins`, and a plain-SQL migration runner
  (`sql/migrations/`, `sitebot migrate`).
- Phase 2, all items: admin dashboard (`/dashboard`), conversation analytics
  (volume, deflection, feedback, top questions), unanswered-questions report,
  lead capture with webhook delivery, human handoff with webhook delivery,
  multilingual answers (reply in the visitor's language), webhook integrations
  (Slack/Zapier/generic), widget customization (avatar, position, suggested
  questions, greeting, colors), answer quality controls (confidence floor,
  canned answers, blocked topics, tone), and source-freshness display.
- Phase 3, core: self-serve signup (`/v1/signup`), Stripe billing scaffolding
  (checkout + webhook plan sync, optional dependency), white-label branding
  flag, answer caching for cost control, and an evaluation harness
  (`evals/run_evals.py`).

Still open from Phase 3: SSO and role-based access, data residency regions,
VPC/on-prem packaging, model routing beyond caching, SOC 2 readiness.

## Phase 0: MVP foundation (in this repo)

Done:

- Polite crawler with sitemap seeding, robots.txt, same-site scoping, page cap.
- Clean content extraction and duplicate-block removal.
- Overlapping chunking with approximate token accounting.
- Pluggable embeddings (OpenAI or local) and pgvector storage per site.
- Grounded retrieval with keyword fallback.
- Streaming answers from Claude with citations, anti-hallucination and
  anti-injection prompt rules.
- FastAPI service: site creation, ingestion, widget config, streaming and
  non-streaming chat, health check, admin key auth, basic rate limiting.
- Dependency-free embeddable widget with Shadow DOM and SSE streaming.
- Docker Compose (Postgres + pgvector + API), CLI, schema, usage metering table.

## Phase 1: Production hardening (weeks 1 to 3)

The goal is that you can safely put a paying customer on it.

| Item | Why | Notes |
| --- | --- | --- |
| Background job queue | Crawls of large sites should not block the web process | Use a worker with a queue (RQ, Celery, or Arq on Redis). Move `ingest_site` off `BackgroundTasks`. |
| Redis-backed rate limiting | Current limiter is per process and resets on restart | Also add per-tenant monthly message quotas enforced at request time. |
| Per-tenant admin auth | Today one global admin key manages all sites | Add tenant accounts, hashed admin keys per tenant, and row scoping so a tenant only sees its own sites. |
| Structured logging and error tracking | You cannot support what you cannot see | JSON logs, request ids, and Sentry or similar for exceptions. |
| Retry and partial-failure handling in ingest | One bad page should not fail a crawl | Already tolerant of fetch and extract failures; add per-embedding retry batching and a failed-URL report. |
| Re-crawl scheduling and incremental refresh | Client content changes | Store per-URL content hash and last-seen; add a nightly or weekly re-crawl that only re-embeds changed pages. |
| Health and readiness probes, graceful shutdown | For container orchestration | `/healthz` exists; add `/readyz` that checks the DB. |
| CORS and secrets discipline | Security | Lock CORS per customer domain; move all keys to a secret manager. |
| Backups and migrations | Data safety | Add a migration tool (Alembic or plain SQL migrations) and automated Postgres backups. |

## Phase 2: Product depth (weeks 3 to 8)

The features that make customers pay and stay.

| Feature | Buyer value | Priority |
| --- | --- | --- |
| Admin dashboard | Self-serve indexing, status, and settings without curl | High |
| Conversation analytics | Volume, top questions, deflection rate, CSAT | High |
| Unanswered-questions report | Shows content gaps; turns the bot into a content strategy tool | High |
| Lead capture | Ask for email when intent is high; deliver leads to CRM or email | High (this is the ROI story) |
| Human handoff | Escalate to email, Slack, or a live agent when the bot cannot help | Medium |
| Multilingual answers | Reply in the visitor's language | Medium (strong for India and global) |
| Integrations | Slack, email, WhatsApp, Zendesk, HubSpot, Intercom | Medium |
| Customization | Colors, avatar, position, custom greeting, suggested questions | Medium |
| Answer quality controls | Confidence threshold, canned answers, blocked topics, tone | Medium |
| Source freshness UI | Show when the knowledge base was last refreshed | Low |

## Phase 3: Scale and platform (weeks 8 and beyond)

Turn it into a business that runs without you in every deal.

| Capability | Purpose |
| --- | --- |
| Self-serve signup and onboarding | Product-led growth without manual setup |
| Stripe billing and metered usage | Subscriptions, overages, invoices, dunning |
| White-label and agency mode | Resellers ship it under their own brand (high leverage) |
| SSO and role-based access | Required by larger buyers |
| Data residency options | India region and EU region for compliance-sensitive buyers |
| VPC or on-prem deployment | Enterprise and regulated customers |
| Model routing and caching | Cheaper answers via caching and smaller models for easy questions |
| Evaluation harness | Automated answer-quality regression tests per release |
| SOC 2 readiness | Unlocks mid-market and enterprise procurement |

## Cross-cutting engineering standards

- Tests: unit tests for chunking, retrieval scoring, and prompt assembly;
  integration tests against a disposable pgvector container; a small answer-quality
  eval set per customer vertical.
- CI/CD: run ruff, mypy strict, and pytest on every push; build and push the
  Docker image; deploy on tag.
- Observability: request tracing, per-tenant usage metrics, cost per message.
- Data governance: retention policy for conversations, PII redaction option, a
  data processing agreement, and a documented deletion path.

## Suggested timeline

| Week | Milestone |
| --- | --- |
| 0 | MVP running; index your own site and three friendly sites |
| 1 to 3 | Phase 1 hardening; put the first design-partner customer live |
| 3 to 8 | Dashboard, analytics, lead capture, unanswered-questions report |
| 8 to 12 | Stripe billing, self-serve signup, white-label mode |
| 12+ | SSO, data residency, evaluation harness, SOC 2 path as demand appears |

## Build versus buy

- Keep building: crawling and extraction, chunking, the grounded prompt, the
  widget, analytics, and the dashboard. These are your product and your moat.
- Consider buying or hosting: the vector store at very large scale, the LLM and
  embedding models, transactional email, billing, and error tracking. Do not
  reinvent these.
