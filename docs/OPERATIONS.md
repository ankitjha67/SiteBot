# Operating SiteBot — Health, Monitoring & Metrics

How to know SiteBot is healthy, catch problems early, and keep costs in check.

## 1. Liveness & readiness

| Endpoint | Meaning | Use for |
| --- | --- | --- |
| `GET /healthz` | Process is up (always 200 if serving) | Load-balancer liveness probe |
| `GET /readyz` | DB reachable (`{"ready": true}`, 200) or not (503) | Load-balancer readiness / deploy gate |

Point an **external uptime monitor** (UptimeRobot, Better Uptime, Pingdom, or a
cron `curl`) at `https://api.yourdomain.com/healthz` every 30–60s and alert on
two consecutive failures. Add `/readyz` to catch DB outages the process survives.

```bash
# quick manual check
curl -fsS https://api.yourdomain.com/healthz && echo OK
curl -fsS https://api.yourdomain.com/readyz
```

## 2. Logs

Structured JSON logs (set `LOG_JSON=true`) with a **request id** on every line,
so one request is traceable end to end. They carry method, path, status, and
latency — never request bodies, keys, or tokens.

```bash
docker compose logs -f api      | grep '"level":"WARNING"'   # warnings/errors
docker compose logs -f worker                                # ingest + cron jobs
```

Ship them to any JSON log store (Loki, CloudWatch, Datadog, ELK). Set
`SENTRY_DSN` to capture exceptions with stack traces and alerting out of the box
(`pip install ".[sentry]"`).

**Watch for these log signals:**

- `SECURITY: ...` at startup → weak admin key or wildcard CORS. Fix before launch.
- `guardian: ... blocked` → the Secrets Guardian stopped a leak/jailbreak.
- `webhook blocked by SSRF guard` / `teams reply blocked` → a misconfigured or
  malicious target was rejected.
- `ingest failed` / `embedding batch ... failed` → crawl or embedding trouble.
- Repeated `429` from a model provider → you hit the provider's rate/quota limit.

## 3. Per-customer health (dashboard + API)

Every site's **Analytics** tab (or `GET /v1/sites/{slug}/analytics`) shows the
numbers that tell you the bot is working *for the customer*:

| Metric | Healthy signal | Where |
| --- | --- | --- |
| Deflection rate | High = bot resolves without humans | analytics summary |
| Unanswered count / report | Low, and the report drives content fixes | Unanswered tab |
| 👍 / 👎 feedback | Positive skew | analytics summary |
| Messages per day | Steady/growing engagement | chart |
| Leads / handoffs | The ROI story | Leads / Handoffs tabs |
| Guard blocks | Should be ~0; spikes = attack attempts | Security tab (`guard_blocks`) |
| Last indexed | Recent = knowledge is fresh | site header |

## 4. Operational metrics to track (platform-wide)

Derive these from logs/DB; they protect uptime and margin:

- **Answer latency** — time from `/v1/chat/stream` request to first token. Rises
  → model provider slow or overloaded.
- **Error rate** — share of chat requests emitting an `error` SSE event.
- **Cache hit rate** — repeated questions served from the answer cache (free).
  Query: rows in `answer_cache` vs `messages`. Low hit rate on repetitive traffic
  = cache TTL too short.
- **Cost per message** — model + embedding spend ÷ answered messages. The core
  margin metric; use caching, smaller/local models, and per-site model choice to
  protect it.
- **Monthly usage vs quota** — `GET /v1/tenants/me` shows `messages_used_this_month`
  vs `monthly_quota`; drives upgrade prompts and overage billing.

Useful direct SQL (read replica or `docker exec ... psql`):

```sql
-- messages answered in the last 24h, platform-wide
SELECT count(*) FROM messages WHERE role='assistant' AND created_at > now()-interval '1 day';
-- answer-cache size per site (free repeat answers)
SELECT site_id, count(*) FROM answer_cache GROUP BY 1 ORDER BY 2 DESC;
-- guard blocks per site
SELECT slug, guard_blocks FROM sites WHERE guard_blocks > 0 ORDER BY guard_blocks DESC;
-- monthly usage per tenant
SELECT tenant_id, count(*) FROM usage_events
 WHERE kind='message' AND created_at >= date_trunc('month', now()) GROUP BY 1 ORDER BY 2 DESC;
```

## 5. Background jobs

The `worker` runs ingestion and three crons: incremental re-crawl (twice hourly),
retention purge (nightly 03:10 UTC), and weekly digests (Mon 08:00 UTC). Confirm
it's alive in its logs; if ingests never leave `queued`, the worker is down or
`REDIS_URL` is misconfigured.

## 6. Backups & data safety

- **Postgres is the only stateful component.** Schedule daily `pg_dump` (or your
  cloud's managed backups) and test a restore. Everything else (API, worker) is
  stateless and disposable.
- **Redis** is a cache/queue; losing it drops in-flight jobs and rate-limit
  windows, not customer data. Enable persistence only if you want queue
  durability across restarts.
- **Retention**: per-site `retention_days` auto-purges old conversations
  (GDPR); document your backup retention to match.

## 7. Scaling & capacity

- **API / worker**: stateless — add replicas behind the load balancer / more
  worker containers. Redis coordinates. On one host, use
  `sitebot serve --workers N` (rule of thumb: CPU cores).
- **DB pool**: `DB_POOL_MIN` / `DB_POOL_MAX` (default 2/20) per process. Keep
  `workers × DB_POOL_MAX` below Postgres `max_connections` (default 100), or
  put PgBouncer in front.
- **Crawler**: fetches `CRAWL_CONCURRENCY` pages in flight (default 4) with
  `CRAWL_DELAY_S` politeness per fetch; the worker runs up to 4 ingests at
  once. A 200-page site indexes in a couple of minutes.
- **Local embeddings**: `EMBED_CONCURRENCY` (default 2) bounds concurrent
  encodes so chat bursts queue briefly instead of thrashing the CPU.
- **Rate limits**: with `REDIS_URL` set, limits are shared across all API
  replicas. Without Redis you get per-process limits (single-instance dev only).
- **Postgres + pgvector**: the growth point. Add the HNSW index (already in the
  schema), scale vertically first, then a read replica for analytics.
- **Model cost at scale**: route easy questions to a cheaper/local model per
  site, keep answer caching on, and use the confidence floor to avoid low-value
  model calls.
- **Measured baseline** (Windows dev laptop, 1 uvicorn worker, local
  embeddings, fast local model): 228 req/s at 200 concurrent chats
  (p50 515 ms), 190 req/s at 400 concurrent (p99 3.1 s), zero failures.
  Against a hosted LLM, per-request latency is dominated by the model; the
  async pipeline holds thousands of in-flight requests either way. Re-measure
  with `python scripts/loadtest.py --key pk_... --n 600 --concurrency 200`
  (raise `RATE_LIMIT_PER_MINUTE` for the bench or it will correctly throttle).

## 7b. Answer-quality evals

Run after any change to chunking, retrieval, prompts, or models:

    python -m sitebot.cli eval <slug> evals/<set>.json            # retrieval only, free
    python -m sitebot.cli eval <slug> evals/<set>.json --answers  # full pipeline, costs model calls

Eval sets are JSON golden questions (see `src/sitebot/evals.py`). The exit
code enforces `--threshold` (default 0.8), so it doubles as a CI gate — CI
seeds `scripts/ci_eval_fixture.py` and requires 100% on
`evals/ci-fixture.json`. Keep one eval set per important customer site.

## 8. Incident quick-reference

| Symptom | First check |
| --- | --- |
| Widget shows "hit an error" | `docker compose logs api | grep WARNING` — the real cause is logged server-side (never sent to the visitor) |
| `/readyz` 503 | Postgres up? `DATABASE_URL` correct? |
| Ingests stuck `queued` | Worker running? `REDIS_URL` set on both api and worker? |
| Answers refuse everything | Secrets Guardian too broad, or confidence floor too high |
| 429s in logs | Model provider quota — add funds, switch provider/model, or rate-limit tenants |
| Channel silent | Webhook URL registered? Signature/verify token correct? (`403`/`401` in logs) |
