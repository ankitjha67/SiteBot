# SiteBot — Complete Deployment Guide (GCP · Oracle · Azure · AWS)

This is the end-to-end guide to take SiteBot from source to a live, HTTPS,
production deployment on any of the four major clouds, then onboard a client
and put the chat widget on their website.

**How to read this:**
- **Part 1** — everything you need *before* you start, and how to get each.
- **Part 2** — the architecture and the two deployment shapes.
- **Part 3** — spin up a server on your chosen cloud (GCP / Oracle / Azure / AWS).
- **Part 4** — the shared deploy steps (identical on every cloud).
- **Part 5** — onboard a client and embed the widget.
- **Part 6** — managed database/cache upgrades per cloud (for scale).
- **Part 7** — operating it: updates, backups, monitoring, costs, troubleshooting.

---

# Part 1 — Requirements beforehand (and how to get them)

Gather these before touching a cloud console. The **Required** ones are
non-negotiable; the rest are optional features.

| # | What | Required? | How to get it |
|---|------|-----------|---------------|
| 1 | **A domain you control** | Yes | Buy from Namecheap / GoDaddy / Cloudflare (~$10/yr). You'll use a subdomain like `bot.yourdomain.com`. You also need **DNS access** to add an A record. |
| 2 | **An LLM API key** | Yes* | One of: **Anthropic** (console.anthropic.com → API Keys, `sk-ant-...`), **OpenAI** (platform.openai.com), **Google Gemini** (aistudio.google.com/apikey). *Or skip and run a **local model** with Ollama (free, no key) — see note below. |
| 3 | **A cloud account** | Yes | GCP / Oracle / Azure / AWS — pick one in Part 3. All have free trials; Oracle has a permanent free tier. |
| 4 | **An SSH key pair** | Yes (VM path) | `ssh-keygen -t ed25519 -C "sitebot"` → creates `~/.ssh/id_ed25519` (private) and `.pub` (public). You paste the **public** key when creating the VM. |
| 5 | **Two strong secrets** | Yes | Generate now: `openssl rand -base64 32` twice — one for `ADMIN_API_KEY`, one for `SECRET_ENCRYPTION_KEY` (encrypts client keys at rest). Store them safely. |
| 6 | **A payment gateway** | Optional | **Razorpay** (India/INR): dashboard.razorpay.com → Settings → API Keys (`rzp_live_...` + secret). **Stripe**: dashboard.stripe.com → API keys. Only needed if you charge clients through SiteBot. |
| 7 | **SMTP credentials** | Optional | For lead/handoff email alerts. Any SMTP provider (SendGrid, Mailgun, Gmail app password). |
| 8 | **Local tools** | Yes | `git` and an SSH client on your machine. (Docker is installed *on the server*, not locally.) |

**Embedding model note:** SiteBot uses **local embeddings** (`EMBED_PROVIDER=local`,
`bge-small-en`, 384 dims) by default in production — free, private, no API key.
For heavily non-English content use `LOCAL_EMBED_MODEL=BAAI/bge-m3` +
`EMBED_DIM=1024`.

**No-LLM option:** SiteBot has an **extractive answer mode** (zero token cost)
and supports **local models** via Ollama (`ANSWER_PROVIDER=openai_compatible`,
`OPENAI_COMPATIBLE_BASE_URL=http://ollama:11434/v1`). So an LLM key is only
strictly required if you want fully-synthesized answers from a hosted model.

---

# Part 2 — Architecture & the two deployment shapes

SiteBot is four pieces:

| Piece | What it is |
|-------|-----------|
| **API** | FastAPI app (the same Docker image), serves the widget, dashboard, and chat |
| **Worker** | Background crawler/ingest jobs (same image, `sitebot worker`) |
| **PostgreSQL + pgvector** | Knowledge base, embeddings, tenants, ledger |
| **Redis** | Job queue, shared rate limiting, scheduled re-crawls |

### Shape A — Single VM + Docker Compose (recommended to start)
One Linux VM runs everything (`docker-compose.prod.yml` bundles Postgres,
Redis, API, Worker, and Caddy for automatic HTTPS). **Works identically on all
four clouds.** ~$10–20/mo. Best for your first deployment and for running many
clients on one box. **This guide's main path.**

### Shape B — Managed services (for scale/HA)
Postgres and Redis become managed cloud services; the API/Worker run on a
container platform (Cloud Run / Container Apps / App Runner / OCI Container
Instances). More resilient, autoscaling, more moving parts. Covered per-cloud
in Part 6.

Start with Shape A. Move to Shape B when one VM isn't enough.

---

# Part 3 — Create a server (pick your cloud)

Each subsection gets you a Linux VM with a **public IP** and ports **22, 80,
443** open. Then everyone converges on Part 4.

## 3A — Google Cloud Platform (GCP)

```bash
gcloud auth login
gcloud config set project YOUR_PROJECT_ID

gcloud compute instances create sitebot-vm \
  --zone=asia-south1-a --machine-type=e2-standard-2 \
  --image-family=ubuntu-2404-lts --image-project=ubuntu-os-cloud \
  --boot-disk-size=30GB --tags=http-server,https-server

# Open HTTP/HTTPS (SSH is open by default)
gcloud compute firewall-rules create allow-web \
  --allow=tcp:80,tcp:443 --target-tags=http-server,https-server

gcloud compute instances describe sitebot-vm --zone=asia-south1-a \
  --format='get(networkInterfaces[0].accessConfigs[0].natIP)'   # your public IP
gcloud compute ssh sitebot-vm --zone=asia-south1-a              # SSH in
```
Region tip: `asia-south1` = Mumbai. Machine `e2-standard-2` = 2 vCPU / 8 GB.

## 3B — Oracle Cloud Infrastructure (OCI) — has a permanent free tier

Oracle's **Always Free** tier includes an Ampere ARM VM (up to 4 OCPU / 24 GB
RAM) that's free forever — genuinely enough to run SiteBot for real.

Console path (easiest for OCI):
1. Sign in → **Compute → Instances → Create instance**.
2. **Image**: Canonical Ubuntu 24.04. **Shape**: `VM.Standard.A1.Flex` (Ampere,
   Always Free eligible) — set 2 OCPU / 12 GB (or up to 4/24 free).
3. **Networking**: create/select a VCN with a public subnet; **assign a public
   IPv4**. Paste your SSH **public** key.
4. Create. Note the **public IP**.
5. **Open ports**: VCN → the subnet's **Security List** → add Ingress rules for
   TCP **80** and **443** from `0.0.0.0/0` (22 is open by default).
6. **Ubuntu firewall (OCI images ship with iptables closed)** — after SSH in:
   ```bash
   sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 80 -j ACCEPT
   sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 443 -j ACCEPT
   sudo netfilter-persistent save
   ```
SSH: `ssh ubuntu@YOUR_PUBLIC_IP`. (ARM note: SiteBot's image builds fine on
ARM; local embeddings run on ARM too.)

## 3C — Microsoft Azure

```bash
az login
az group create --name sitebot-rg --location centralindia

az vm create --resource-group sitebot-rg --name sitebot-vm \
  --image Ubuntu2404 --size Standard_B2s \
  --admin-username azureuser --ssh-key-values ~/.ssh/id_ed25519.pub \
  --public-ip-sku Standard

# Open HTTP/HTTPS
az vm open-port --resource-group sitebot-rg --name sitebot-vm --port 80 --priority 900
az vm open-port --resource-group sitebot-rg --name sitebot-vm --port 443 --priority 901

az vm show -d -g sitebot-rg -n sitebot-vm --query publicIps -o tsv   # public IP
ssh azureuser@THAT_IP
```
`centralindia` = Pune. `Standard_B2s` = 2 vCPU / 4 GB.

## 3D — Amazon Web Services (AWS)

Simplest is **Lightsail** (fixed price, batteries included):
1. Lightsail console → **Create instance** → Linux/Unix → **Ubuntu 24.04** →
   plan **$12/mo (2 GB)** or **$24 (4 GB, recommended)** → Create.
2. **Networking** tab → **IPv4 Firewall** → add rules for **HTTP (80)** and
   **HTTPS (443)**. Attach a **static IP** (Networking → Create static IP).
3. Download the default key or add your own; SSH: `ssh -i key.pem ubuntu@STATIC_IP`.

Or **EC2** via CLI:
```bash
aws ec2 run-instances --image-id RESOLVE:ssm:/aws/service/canonical/ubuntu/server/24.04/stable/current/amd64/hvm/ebs-gp3/ami-id \
  --instance-type t3.small --key-name YOUR_KEYPAIR \
  --security-groups sitebot-sg --count 1
# create the SG first with inbound 22/80/443 (aws ec2 authorize-security-group-ingress)
```

---

# Part 4 — Deploy on the server (identical on every cloud)

You're now SSH'd into a fresh Ubuntu VM with a public IP. Do this once.

### 1. DNS — point a subdomain at the VM
In your domain's DNS, add an **A record**:

| Type | Name | Value |
|------|------|-------|
| A | `bot` | `<the VM's public IP>` |

Now `bot.yourdomain.com` resolves to the server. Wait a minute for propagation.

### 2. Install Docker
```bash
curl -fsSL https://get.docker.com | sh
```

### 3. Get the code and configure
```bash
git clone https://github.com/ankitjha67/SiteBot.git
cd SiteBot/sitebot
cp .env.example .env
nano .env
```
Set at minimum:
```ini
SITEBOT_DOMAIN=bot.yourdomain.com
ADMIN_API_KEY=<paste: openssl rand -base64 32>
SECRET_ENCRYPTION_KEY=<paste: openssl rand -base64 32>
POSTGRES_PASSWORD=<paste: openssl rand -base64 24>
ANSWER_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...
EMBED_PROVIDER=local
EMBED_DIM=384
# Optional India payments:
# RAZORPAY_KEY_ID=...   RAZORPAY_KEY_SECRET=...   BILLING_CURRENCY=inr
```

### 4. Launch (automatic HTTPS)
```bash
sudo docker compose -f docker-compose.prod.yml up -d --build
```
Caddy provisions a Let's Encrypt certificate for your domain automatically.
After ~30 seconds:
```bash
curl https://bot.yourdomain.com/healthz      # -> {"ok":true}
```
✅ Console: `https://bot.yourdomain.com/dashboard`
✅ Onboarding: `https://bot.yourdomain.com/onboarding`

> If the cert doesn't issue: confirm the A record resolves (`dig bot.yourdomain.com`)
> and ports 80+443 are open (recheck the cloud firewall AND, on Oracle, the VM's
> iptables). Caddy needs port 80 reachable to complete the ACME challenge.

---

# Part 5 — Onboard a client and embed the widget

1. Open `https://bot.yourdomain.com/onboarding`, unlock with your `ADMIN_API_KEY`.
2. Fill in the client: **name**, their **website URL** (SiteBot crawls it),
   pick an agent, set the **LLM key**, toggle the features they're paying for,
   and any extra seed URLs. **Save** — it crawls the site and returns a
   **public key** (`pk_...`), an **embed snippet**, and the client's own
   **dashboard key** (shown once).
3. Set their plan (Business, etc.) in **Team → Plan & Features** or via
   `POST /v1/tenants/{id}/plan {"bundle":"business"}` with the admin key.
4. **Embed on the client's site** — paste before `</body>`:
   ```html
   <script src="https://bot.yourdomain.com/widget.js"
           data-key="pk_THEIR_KEY"
           data-api="https://bot.yourdomain.com"></script>
   ```
   For a **Next.js** site, use the `<Script>` component in the root layout
   (`strategy="afterInteractive"`). For WordPress, paste into the theme footer
   or a "custom HTML" block.
5. Done — the widget appears on every page, auto-branded to the client's colour
   and font, answering from their crawled content, with lead capture, booking,
   and the Secrets Guardian active per your config.

---

# Part 6 — Managed database & cache upgrades (for scale)

Shape A runs Postgres and Redis as containers on the VM — fine to thousands of
conversations. When you want managed backups/HA, move them off the box. Point
`DATABASE_URL` and `REDIS_URL` in `.env` at the managed endpoints and remove the
`db`/`redis` services from the compose file.

**pgvector must be enabled** on the managed Postgres (`CREATE EXTENSION vector;`).

| Cloud | Managed Postgres (pgvector) | Managed Redis |
|-------|-----------------------------|---------------|
| **GCP** | Cloud SQL for PostgreSQL (`CREATE EXTENSION vector`) | Memorystore for Redis |
| **Azure** | Azure DB for PostgreSQL Flexible Server (allowlist `vector` in Server parameters, then `CREATE EXTENSION`) | Azure Cache for Redis |
| **AWS** | RDS for PostgreSQL or Aurora PostgreSQL (pgvector supported; `CREATE EXTENSION vector`) | ElastiCache for Redis |
| **Oracle** | OCI Database with PostgreSQL — verify pgvector availability in your region; if unavailable, keep Postgres in the container on the VM | OCI Cache (Redis-compatible), or keep Redis in the container |

For the API/Worker themselves, the container-native option per cloud is:
GCP **Cloud Run** (see `docs/GCP_DEPLOYMENT.md`), Azure **Container Apps**, AWS
**App Runner** or **ECS Fargate**, OCI **Container Instances**. All run the same
image; give them the managed `DATABASE_URL`/`REDIS_URL` + the same env/secrets,
and keep the worker as a single always-on instance.

---

# Part 7 — Operating it

### Updating SiteBot
```bash
cd SiteBot/sitebot && git pull
sudo docker compose -f docker-compose.prod.yml up -d --build
```
Migrations run automatically on API startup. Every embedded widget gets the new
version on the next page load. For **push-to-deploy**, add the four repo secrets
and use `.github/workflows/deploy.yml` (see `docs/GO_LIVE.md`).

### Backups
Client data lives in the `sitebot_pgdata` Docker volume. Either snapshot the VM
disk on a schedule (all four clouds support this), or cron a `pg_dump`:
```bash
docker exec sitebot-db-1 pg_dump -U sitebot sitebot | gzip > backup-$(date +%F).sql.gz
```

### Monitoring
- Liveness `GET /healthz`, readiness `GET /readyz`.
- Prometheus metrics at `GET /metrics` (scrape with Managed Prometheus / Grafana Cloud).
- Per-client analytics + the admin billing/ledger/audit console are in the dashboard.

### Rough monthly cost to start
| Cloud | VM (Shape A) | Notes |
|-------|--------------|-------|
| **Oracle** | **$0** | Always Free Ampere A1 (4 OCPU/24 GB) — best value to start |
| **AWS** | ~$12–24 | Lightsail fixed price |
| **GCP** | ~$15 | e2-small/standard-2 |
| **Azure** | ~$15 | B2s |

Plus your LLM usage (local embeddings are free; extractive mode is $0 tokens).
One VM runs aiing.in plus many more clients.

### Troubleshooting
| Symptom | Check |
|---|---|
| `/healthz` unreachable | Cloud firewall AND (Oracle) VM iptables allow 80/443; `docker compose ps` all healthy |
| No HTTPS cert | A record resolves? Port 80 reachable for the ACME challenge? `docker compose logs caddy` |
| Widget silent on site | `data-api` points at `https://bot.yourdomain.com`? Site's domain in the client's allowed-origins? |
| Answers say "I don't have that" | Crawl succeeded? (dashboard → the site → pages indexed) Re-crawl if the site changed |
| Bad signature on payment webhook | Webhook secret in `.env` matches the gateway dashboard |

---

## Where to go next
- `docs/GO_LIVE.md` — condensed VM quick-start + the widget `<Script>` snippet.
- `docs/GCP_DEPLOYMENT.md` — the managed Cloud Run + Cloud SQL path in detail.
- `docs/OPERATIONS.md` — scaling knobs, quotas, eval harness, incident reference.
- `docs/PRICING.md` / `docs/GTM_MONETIZATION.md` — packaging and monetisation.
