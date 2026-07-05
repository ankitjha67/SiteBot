# Security & Compliance Audit

Expert-level sweep of the entire SiteBot repository for secret leakage,
injection, access control, and data-handling issues. Date: 2026-07-04.

## Summary

Full-repo review across secrets management, injection surfaces, authentication
and authorization, SSRF, XSS, RCE, logging, and outbound TLS. **Five issues were
found and fixed**; the remaining surfaces were verified clean. Four items are
operator responsibilities (they cannot be fixed in code) and are listed under
Action Required.

## Findings fixed

| # | Severity | Issue | Fix | Verified |
| --- | --- | --- | --- | --- |
| 1 | High | `GET /v1/sites/{slug}/actions` returned AI-Action static **headers in full** — these hold third-party API keys, and the create UI promised they are "never exposed". Any team member (incl. read-only viewers) could read them. | Header **values are masked** (`••••••`) in the API response; real values stay server-side for execution and are returned to no client. | Live: `Authorization: Bearer …` → `••••••` |
| 2 | Medium | Owner-supplied **webhook URLs** (`lead_webhook_url`, `handoff_webhook_url`, `digest_webhook_url`) were POSTed to with no host check — blind SSRF to cloud metadata (`169.254.169.254`) or internal services from a tenant account. | `is_safe_url()` SSRF guard applied at save time (PATCH → 400 for private hosts) **and** re-checked at send time; webhook delivery now uses `follow_redirects=False` to stop 30x bounces to internal hosts. | Live: metadata IP → 400, localhost → 400, Slack → 200 |
| 3 | Medium | `/v1/chat/stream` streamed the **internal exception text** (`str(exc)[:200]`) to the public visitor on error — could disclose DB/provider internals. | Real cause is logged server-side; the visitor receives a generic "please try again". | Code + unit |
| 4 | Low | `GET /v1/sites/{slug}` returned the raw **protected-secret values to read-only viewer** team keys. | Secret values are masked for the `viewer` role; admins still see them to edit. | Live: viewer → `••••••`, admin → values |
| 5 | Low | Webhook delivery followed redirects (SSRF bypass of #2). | `follow_redirects=False` on webhook + action HTTP clients. | Code |

Additional hardening added: startup **warnings** when `ADMIN_API_KEY` is a
default/short value or `CORS_ORIGINS` is `*`.

## Surfaces verified clean

- **No hardcoded secrets in source.** The only real credential on disk is the
  operator's own `.env`, which is gitignored; grep across the tree for key
  patterns (`sk-…`, `AIza…`, `xox[bp]-`, `ghp_…`, `AKIA…`) found nothing in
  tracked source. (`.env` itself — see Action Required.)
- **No SQL injection.** All queries are asyncpg parameterized (`$1`…). The two
  dynamically-built statements (`update_site` SET clause, `list_actions` WHERE)
  interpolate only fixed column names from Pydantic model fields, never user
  values.
- **No RCE vectors.** No `eval`, `exec`, `pickle`, `os.system`, `subprocess`,
  `yaml.load`, or `__import__` anywhere. The `.sql` dump importer parses INSERT
  rows as text with regex — it never executes SQL.
- **No XSS in the widget.** Answer content is HTML-escaped by `format()` before
  its single `innerHTML` insertion; markdown-lite (bold/code) and citation
  links wrap already-escaped text, and source URLs pass through `escapeAttr`.
  All other message rendering uses `textContent`.
- **No secret logging.** Structured logs carry method/path/status/request-id
  only — never request bodies, keys, or tokens.
- **Channel tokens never leave the server.** `GET /v1/sites/{slug}` returns
  `*_connected` booleans, not the Telegram/Slack/WhatsApp/Twilio/Messenger/Teams
  credentials. The public widget-config endpoint exposes only theme/behaviour.
- **All inbound channel webhooks are signature-verified**: Slack (v0 HMAC +
  5-min replay window), WhatsApp/Messenger (`X-Hub-Signature-256`), Telegram
  (secret-token), Twilio (HMAC-SHA1), Stripe (webhook signature). Teams requires
  a bearer token (see Residual).
- **SSRF guard on AI Actions and webhooks** blocks loopback, private, link-local,
  reserved, multicast, and the cloud-metadata IP (`169.254.169.254`,
  `metadata.google.internal`) — unit-tested.
- **Auth**: global admin key compared in constant time (`secrets.compare_digest`);
  tenant and team keys stored as SHA-256 hashes only; team keys carry an
  admin/viewer role enforced on every mutating endpoint.
- **Abuse limits**: per-key+IP rate limiting (Redis-backed, shared across
  instances), monthly plan quotas, 20 MB upload cap (413), per-site CORS origin
  lock, `MAX_PAGES` crawl cap.
- **Secrets Guardian**: confidential content is filtered from retrieval and
  deterministically scanned out of every answer even under a jailbroken model
  (separately verified live).
- **Outbound TLS**: every external API call (Telegram, Slack, Meta, Twilio,
  Microsoft, Stripe, model/embedding providers) uses `https://`.
- **Not committable**: `.env` is gitignored and the working tree is not a git
  repo, so no secret has been committed.

## Action required (operator)

1. **Rotate the Gemini API key.** The key in `sitebot/.env` was pasted into a
   support session and should be considered exposed. Regenerate it at
   <https://aistudio.google.com/apikey> and update `.env`. `.env` is gitignored;
   never commit it.
2. **Set a strong `ADMIN_API_KEY`** (32+ random chars) before exposing the
   service. The startup log now warns if it is a default or short value.
3. **Lock `CORS_ORIGINS`** to your customers' domains in production (currently
   `*` for local development; startup warns).
4. **Provide SMTP over TLS** if using email alerts (`SMTP_USE_TLS=true`, the
   default) and store `SMTP_PASSWORD` in a secret manager, not plaintext `.env`,
   in production.

## Residual / documented limitations

- **Microsoft Teams inbound** — RESOLVED. The endpoint now fully validates the
  Bot Framework JWT: RS256 signature against Microsoft's published signing keys
  (`login.botframework.com` JWKS, cached), issuer `https://api.botframework.com`,
  audience = the bot's app id, and expiry. Outbound replies are additionally
  restricted to Bot Framework service hosts so a signed activity cannot redirect
  our bearer token elsewhere. Requires the `teams` extra (`pip install ".[teams]"`).
- **SSRF guard TOCTOU**: `is_safe_url` resolves DNS at check time; a domain that
  later re-points to an internal IP is a known (advanced) residual. Mitigated by
  re-checking at send time and disabling redirects; a network egress policy is
  the belt-and-suspenders control in production.
- **Data retention / GDPR**: per-site retention purge and a documented deletion
  path exist; operators should also configure Postgres backups' retention and a
  DPA per the GTM plan.
