# Making SiteBot live (worked example: aiing.in)

Right now SiteBot runs on your laptop (`localhost`), which the public internet
can't reach — so the widget on a real website has nothing to talk to. Going
live means three things:

1. Run SiteBot on a **public server with HTTPS on a domain** you control.
2. **Onboard the client** on that live instance (crawl their site there).
3. Paste **one script tag** into the client's website.

`docker-compose.prod.yml` + `Caddyfile` make step 1 turnkey: automatic
Let's Encrypt HTTPS, no nginx wrangling.

---

## Step 1 — Get a server (~10 min)

Any Linux VM with a public IP works — DigitalOcean, AWS Lightsail, Hetzner,
or GCP (`e2-small`, ~$15/mo; asia-south1 / Mumbai is closest for aiing.in).
2 vCPU / 2–4 GB RAM is plenty to start. Note its **public IP**.

Install Docker on it:
```bash
curl -fsSL https://get.docker.com | sh
```

## Step 2 — Point a domain at it (~5 min, DNS)

You own `aiing.in`, so add a subdomain for the bot. In your DNS provider add:

| Type | Name | Value |
|------|------|-------|
| A | `bot` | `<your server's public IP>` |

That makes `bot.aiing.in` resolve to the server. (Any subdomain is fine —
`bot`, `chat`, `assistant`.)

## Step 3 — Deploy (~5 min)

On the server:
```bash
git clone https://github.com/ankitjha67/SiteBot.git
cd SiteBot/sitebot
cp .env.example .env
nano .env        # fill in the PRODUCTION section (below)
docker compose -f docker-compose.prod.yml up -d --build
```

Minimum `.env` values to set:
```ini
SITEBOT_DOMAIN=bot.aiing.in
ADMIN_API_KEY=$(openssl rand -base64 32)          # paste the output
SECRET_ENCRYPTION_KEY=$(openssl rand -base64 32)  # paste the output
POSTGRES_PASSWORD=$(openssl rand -base64 24)      # paste the output
ANSWER_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...                       # your LLM key
EMBED_PROVIDER=local
EMBED_DIM=384
```

Caddy fetches a TLS cert automatically. In ~30 seconds:
```bash
curl https://bot.aiing.in/healthz     # -> {"ok":true}
```
Your console is now at **https://bot.aiing.in/dashboard** and onboarding at
**https://bot.aiing.in/onboarding**.

> Ports 80 and 443 must be open in the server's firewall/security group.

## Step 4 — Onboard aiing.in on the live instance

The client you set up locally lives in your laptop's database — it doesn't
travel. Re-onboard on the live server (2 minutes):

1. Open `https://bot.aiing.in/onboarding`, unlock with your `ADMIN_API_KEY`.
2. Name **AI ING**, domain **https://aiing.in**, pick the agent, set the LLM
   key, turn on the features you want, Save. It crawls aiing.in and gives you a
   **public key** (`pk_...`) and the embed snippet.
3. (Business tier) Set the plan: in the dashboard Team → Plan & Features, or via
   `POST /v1/tenants/{id}/plan {"bundle":"business"}` with the admin key.

## Step 5 — Add the widget to aiing.in

aiing.in is a Next.js app, so add the script once in the root layout. In
`app/layout.tsx` (App Router), just before `</body>`:

```tsx
import Script from "next/script";
// ...inside <body>, after {children}:
<Script
  src="https://bot.aiing.in/widget.js"
  data-key="pk_YOUR_PUBLIC_KEY"
  data-api="https://bot.aiing.in"
  strategy="afterInteractive"
/>
```
(Pages Router: put the same `<script ...></script>` in `pages/_document.tsx`
inside `<body>`.) Deploy aiing.in. The widget appears on every page,
auto-branded to your purple, answering from your crawled content.

## Step 6 — Verify live

- Visit `https://aiing.in` → the "Ask Aria" bubble is bottom-right.
- Ask "What is OverlapX?" → cited answer.
- Leave a lead → it appears in `https://bot.aiing.in/dashboard`.

---

## Operating it

- **Update SiteBot**: `git pull && docker compose -f docker-compose.prod.yml up -d --build`. All embedded widgets get the new version on next page load.
- **Re-crawl when aiing.in changes**: dashboard → the site → Re-crawl (or set an auto re-crawl interval).
- **Backups**: the Postgres data lives in the `sitebot_pgdata` volume — snapshot the VM or `pg_dump` on a cron.
- **Payments (India)**: add `RAZORPAY_KEY_ID` / `RAZORPAY_KEY_SECRET` to `.env`, restart, and register the webhook `https://bot.aiing.in/v1/billing/razorpay/webhook` in the Razorpay dashboard.
- **Scale later**: when one VM isn't enough, move Postgres/Redis to managed services and run the API on Cloud Run — see `docs/GCP_DEPLOYMENT.md`.

## Costs to start
One `e2-small`/Lightsail VM with everything on it: **~$15/mo** + your LLM
usage. Local embeddings are free. That runs aiing.in plus many more clients.
