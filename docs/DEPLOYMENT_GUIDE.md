# SiteBot Deployment & Customer Onboarding Guide

End-to-end: stand up the platform once, then put a working, grounded chatbot on
any customer's website in minutes. Two audiences:

- **Platform operator (you)** — sections 1–3, done once.
- **Per customer** — sections 4–7, repeated per client (or self-serve).

---

## 1. Prerequisites

| Need | Why | Notes |
| --- | --- | --- |
| A Linux server / VM (2 vCPU, 4 GB RAM to start) | Runs the API, worker, Postgres, Redis | Any cloud (AWS/GCP/DigitalOcean/Hetzner) or on-prem |
| A domain + DNS control | `api.yourdomain.com` for the API, optional `cdn.yourdomain.com` for the widget | TLS is mandatory (channels require HTTPS) |
| Docker + Docker Compose | One-command bring-up | `docker compose up` starts db + redis + api + worker |
| An answer-model key **or** a local model | Generates answers | Anthropic / OpenAI / Gemini key, **or** Ollama running Qwen/Llama (zero API cost) |
| An embeddings option | Vectorizes content | OpenAI `text-embedding-3-small`, **or** local `sentence-transformers` (`EMBED_PROVIDER=local`) |

---

## 2. Stand up the platform (once)

```bash
git clone <your repo> && cd sitebot
cp .env.example .env
```

Edit `.env` — the security-critical values:

```bash
ADMIN_API_KEY=<32+ random chars>          # openssl rand -hex 24
DATABASE_URL=postgresql://sitebot:<strong-pw>@db:5432/sitebot
REDIS_URL=redis://redis:6379/0
PUBLIC_BASE_URL=https://api.yourdomain.com # required for channel webhooks
CORS_ORIGINS=https://app.yourdomain.com    # lock this down (not *)

# Answer model — pick ONE path:
ANSWER_PROVIDER=anthropic                   # or openai / gemini / openai_compatible
ANTHROPIC_API_KEY=...
# Local/offline instead:
# ANSWER_PROVIDER=openai_compatible
# OPENAI_COMPATIBLE_BASE_URL=http://host.docker.internal:11434/v1
# ANSWER_MODEL=qwen2.5

EMBED_PROVIDER=openai                        # or local
OPENAI_API_KEY=...

# Optional: email alerts, Sentry, Stripe billing
SMTP_HOST=smtp.sendgrid.net
SMTP_USER=apikey
SMTP_PASSWORD=...
SENTRY_DSN=...
```

Bring it up:

```bash
docker compose up -d --build          # db, redis, api (:8000), worker
docker compose logs -f api            # watch for the SECURITY warnings — heed them
```

**Put TLS in front.** Terminate HTTPS with Caddy, nginx, or a cloud load
balancer pointed at the API on port 8000. Minimal Caddy:

```
api.yourdomain.com {
    reverse_proxy localhost:8000
}
```

Point DNS `api.yourdomain.com` → your server. Verify:

```bash
curl https://api.yourdomain.com/healthz     # {"ok": true}
curl https://api.yourdomain.com/readyz      # {"ready": true}  (checks the DB)
```

**Scale later** by running more `api` replicas behind the load balancer and more
`worker` replicas — both are stateless; Redis coordinates rate limits and the
job queue. Postgres is the one stateful component: back it up (section in
OPERATIONS.md).

---

## 3. Host the widget

The API already serves it at `https://api.yourdomain.com/widget.js`. For best
performance put it (and cache it) on a CDN, but the API-served path works out of
the box and is what the dashboard's embed snippet uses.

---

## 4. Create a customer (per client)

Two ways:

**A. You provision it (agency / done-for-you):**

```bash
# Create a tenant (a billable customer account) — returns a tk_ key, shown once
curl -X POST https://api.yourdomain.com/v1/tenants \
  -H "X-API-Key: $ADMIN_API_KEY" -H "Content-Type: application/json" \
  -d '{"name":"Acme Inc","email":"ops@acme.com","plan":"growth"}'
```

**B. Self-serve:** send them to `https://api.yourdomain.com/v1/signup` (or a
signup page that calls it) — they get a free-plan tenant key instantly.

The tenant then uses the **dashboard** at `https://api.yourdomain.com/dashboard`,
pastes their `tk_` key, and does everything below in the UI. The API calls below
show what the dashboard does under the hood.

---

## 5. Index the customer's knowledge

```bash
TK=tk_...   # the tenant key

# Create a site (returns a pk_ public/widget key)
curl -X POST https://api.yourdomain.com/v1/sites \
  -H "X-API-Key: $TK" -H "Content-Type: application/json" \
  -d '{"name":"Acme","start_url":"https://www.acme.com","display_name":"Acme Assistant"}'

# Crawl + index (runs on the worker)
curl -X POST https://api.yourdomain.com/v1/sites/www-acme-com/ingest -H "X-API-Key: $TK"

# Poll status until "ready"
curl https://api.yourdomain.com/v1/sites/www-acme-com -H "X-API-Key: $TK"
```

Add knowledge beyond the crawl in the dashboard's **Knowledge** tab (or the
`/v1/sites/{slug}/sources` API): PDF/DOCX/TXT/CSV/HTML/JSON uploads, **`.sql`
database dumps**, raw text, and Q&A pairs. Re-crawls are incremental and can be
scheduled (`recrawl_hours`).

---

## 6. Configure behaviour (dashboard → Settings / Security / Actions)

- **Appearance:** name, theme color, avatar (+ pulse/bounce animation), position,
  welcome message, suggested questions, widget language.
- **Answer quality:** model provider/model, conversation memory turns, tone,
  confidence floor, canned answers, blocked topics, custom instructions.
- **Lead capture & handoff:** enable, prompt, webhook and/or email alerts.
- **Security (Secrets Guardian):** list literal secrets and confidential topics
  the bot must never reveal. **Set `allowed_origins`** to the customer's
  domain(s) so the widget only answers from their site.
- **Actions:** HTTP lookups (order status, CRM) and link hand-offs (booking).
- **Voice:** on by default in the widget (mic + speaker).

---

## 7. Install the widget on the customer's site

Copy the snippet from the dashboard (site header → **Install**):

```html
<script src="https://api.yourdomain.com/widget.js"
        data-key="pk_ACME_PUBLIC_KEY"
        data-api="https://api.yourdomain.com"></script>
```

Paste it **before `</body>`**. Platform-specific:

| Platform | Where to paste |
| --- | --- |
| **WordPress** | Appearance → Theme File Editor → `footer.php` before `</body>`, or a "insert headers and footers" plugin, or a Custom HTML block |
| **Shopify** | Online Store → Themes → Edit code → `theme.liquid`, before `</body>` |
| **Webflow** | Project Settings → Custom Code → Footer Code |
| **Wix** | Settings → Custom Code → add to Body – end, all pages |
| **Squarespace** | Settings → Advanced → Code Injection → Footer |
| **Custom / React / Next** | Add the `<script>` to the root HTML template or inject once on mount |

The widget reads its theme, language, avatar, and feature flags from the server,
so you can change any of it from the dashboard **without touching the customer's
site again**.

### Optional: connect messaging channels

In the dashboard's Channels section, paste credentials and set the shown webhook
URL in each provider's console:

- **Telegram** — bot token from @BotFather (webhook auto-registered if
  `PUBLIC_BASE_URL` is set).
- **WhatsApp / Messenger / Instagram** — Meta app token, verify token, app secret.
- **Slack** — bot token + signing secret; point event subscriptions at the URL.
- **SMS (Twilio)** — account SID, auth token, from number; set the number's
  inbound webhook.
- **Microsoft Teams** — Bot app id + password (install the `teams` extra).

---

## 8. Go-live checklist

- [ ] TLS valid on `api.yourdomain.com`; `/healthz` and `/readyz` green.
- [ ] `ADMIN_API_KEY` is strong; `CORS_ORIGINS` locked (no startup warnings).
- [ ] Each site has `allowed_origins` set to the customer's domain.
- [ ] Secrets Guardian configured for any site handling confidential data.
- [ ] Answer-model key funded (or local model running); embeddings working.
- [ ] Postgres backups scheduled; Redis persistence as needed.
- [ ] Uptime monitor pinging `/healthz`; Sentry (or logs) capturing errors.
- [ ] A few real questions tested in the dashboard **Playground** per site.
