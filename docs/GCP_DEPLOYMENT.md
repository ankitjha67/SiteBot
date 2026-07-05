# Deploying SiteBot to Google Cloud Platform

This takes you from "runs on my laptop with Docker Desktop" to a real,
always-on cloud deployment. Two options — pick by how much you want to manage:

| | **Option A — Cloud Run (recommended)** | **Option B — one VM** |
|---|---|---|
| Effort | Low; Google runs the containers | Medium; you run one server |
| Scaling | Automatic (0 → N) | Manual (resize the VM) |
| Cost at rest | ~$0 (scales to zero) + DB | Fixed (~$15–40/mo) |
| Best for | Production, growth | Cheapest fixed cost, full control |

Both use the **same Docker image** you already have (`Dockerfile`). Nothing in
the code changes — only environment variables and where Postgres/Redis live.

---

## What moves to managed services

On your laptop these are Docker containers; in the cloud use managed equivalents
so you never babysit a database:

| Local (Docker Desktop) | Google Cloud |
|---|---|
| `sitebot-db` (pgvector) | **Cloud SQL for PostgreSQL** (enable the `vector` extension) |
| `sitebot-redis` | **Memorystore for Redis** |
| API container | **Cloud Run** service (or a VM) |
| worker container | **Cloud Run** service / job (or same VM) |
| widget + dashboard | served by the API; front with **Cloud CDN** (optional) |
| secrets in `.env` | **Secret Manager** |

---

## Prerequisites (once)

```bash
gcloud auth login
gcloud config set project YOUR_PROJECT_ID
gcloud services enable run.googleapis.com sqladmin.googleapis.com \
    redis.googleapis.com secretmanager.googleapis.com \
    artifactregistry.googleapis.com vpcaccess.googleapis.com
```

---

## Step 1 — Postgres (Cloud SQL + pgvector)

```bash
gcloud sql instances create sitebot-db \
    --database-version=POSTGRES_16 --tier=db-custom-1-3840 \
    --region=asia-south1 --storage-auto-increase        # asia-south1 = Mumbai
gcloud sql databases create sitebot --instance=sitebot-db
gcloud sql users create sitebot --instance=sitebot-db --password=STRONG_DB_PASSWORD
```

Enable pgvector once (Cloud SQL supports it):
```bash
gcloud sql connect sitebot-db --user=sitebot --database=sitebot
# then in the psql prompt:
CREATE EXTENSION IF NOT EXISTS vector;
\q
```
SiteBot creates its tables and runs migrations automatically on first boot.

## Step 2 — Redis (Memorystore)

```bash
gcloud redis instances create sitebot-redis \
    --size=1 --region=asia-south1 --redis-version=redis_7_0
gcloud redis instances describe sitebot-redis --region=asia-south1 \
    --format='value(host,port)'      # note the private IP + port
```
Memorystore is private-IP only, so Cloud Run reaches it through a connector:
```bash
gcloud compute networks vpc-access connectors create sitebot-conn \
    --region=asia-south1 --range=10.8.0.0/28
```

## Step 3 — Secrets (Secret Manager)

Never put keys in the image. Store them once:
```bash
printf 'STRONG_RANDOM' | gcloud secrets create ADMIN_API_KEY --data-file=-
printf 'STRONG_RANDOM' | gcloud secrets create SECRET_ENCRYPTION_KEY --data-file=-
printf 'sk-ant-...'    | gcloud secrets create ANTHROPIC_API_KEY --data-file=-
printf 'rzp_live_...'  | gcloud secrets create RAZORPAY_KEY_ID --data-file=-
printf 'razor_secret'  | gcloud secrets create RAZORPAY_KEY_SECRET --data-file=-
# add STRIPE_SECRET_KEY, RAZORPAY_WEBHOOK_SECRET, etc. the same way
```

## Step 4 — Build & push the image

```bash
gcloud artifacts repositories create sitebot --repository-format=docker --location=asia-south1
gcloud builds submit --tag \
    asia-south1-docker.pkg.dev/YOUR_PROJECT_ID/sitebot/api:latest
```

## Step 5 — Deploy the API (Cloud Run)

```bash
DB_CONN=$(gcloud sql instances describe sitebot-db --format='value(connectionName)')
REDIS_HOST=... ; REDIS_PORT=6379   # from Step 2

gcloud run deploy sitebot-api \
  --image asia-south1-docker.pkg.dev/YOUR_PROJECT_ID/sitebot/api:latest \
  --region asia-south1 --allow-unauthenticated \
  --add-cloudsql-instances "$DB_CONN" \
  --vpc-connector sitebot-conn \
  --set-env-vars "DATABASE_URL=postgresql://sitebot:STRONG_DB_PASSWORD@/sitebot?host=/cloudsql/$DB_CONN" \
  --set-env-vars "REDIS_URL=redis://$REDIS_HOST:$REDIS_PORT/0" \
  --set-env-vars "EMBED_PROVIDER=local,EMBED_DIM=384,ANSWER_PROVIDER=anthropic" \
  --set-env-vars "PUBLIC_BASE_URL=https://YOUR_DOMAIN" \
  --set-secrets "ADMIN_API_KEY=ADMIN_API_KEY:latest,SECRET_ENCRYPTION_KEY=SECRET_ENCRYPTION_KEY:latest,ANTHROPIC_API_KEY=ANTHROPIC_API_KEY:latest,RAZORPAY_KEY_ID=RAZORPAY_KEY_ID:latest,RAZORPAY_KEY_SECRET=RAZORPAY_KEY_SECRET:latest" \
  --cpu 2 --memory 2Gi --min-instances 1 --max-instances 10 --port 8000
```

`--min-instances 1` keeps the local embedding model warm (avoids a cold-start
on the first chat). Drop to 0 to save money if you use a hosted embed provider.

## Step 6 — Deploy the worker

The worker needs no inbound traffic. Run it as a second Cloud Run service that
never scales to zero:
```bash
gcloud run deploy sitebot-worker \
  --image asia-south1-docker.pkg.dev/YOUR_PROJECT_ID/sitebot/api:latest \
  --region asia-south1 --no-cpu-throttling --min-instances 1 --max-instances 1 \
  --add-cloudsql-instances "$DB_CONN" --vpc-connector sitebot-conn \
  --command sitebot --args worker \
  --set-env-vars "DATABASE_URL=...,REDIS_URL=..." \
  --set-secrets "SECRET_ENCRYPTION_KEY=SECRET_ENCRYPTION_KEY:latest,ANTHROPIC_API_KEY=ANTHROPIC_API_KEY:latest"
```
(Same env/secrets as the API.)

## Step 7 — Domain, HTTPS, webhooks

```bash
gcloud run domain-mappings create --service sitebot-api \
    --domain api.yourdomain.com --region asia-south1
```
Cloud Run gives you managed HTTPS automatically. Then point the clients'
embed snippet at it:
```html
<script src="https://api.yourdomain.com/widget.js" data-key="pk_..."
        data-api="https://api.yourdomain.com"></script>
```
Register webhooks with this base URL:
- Razorpay dashboard → Webhooks → `https://api.yourdomain.com/v1/billing/razorpay/webhook`
- Stripe → `https://api.yourdomain.com/v1/billing/webhook`
- Channel webhooks (Telegram/WhatsApp/etc.) already use `PUBLIC_BASE_URL`.

---

## Option B — single VM (cheapest fixed cost)

If you'd rather run one box with the existing `docker-compose.yml`:

```bash
gcloud compute instances create sitebot-vm \
    --machine-type e2-standard-2 --zone asia-south1-a \
    --image-family ubuntu-2404-lts --image-project ubuntu-os-cloud \
    --tags http-server,https-server --boot-disk-size 30GB
# SSH in:
gcloud compute ssh sitebot-vm --zone asia-south1-a
# on the VM:
sudo apt update && sudo apt install -y docker.io docker-compose-plugin git
git clone https://github.com/ankitjha67/SiteBot.git && cd SiteBot/sitebot
cp .env.example .env && nano .env        # fill in keys
sudo docker compose up -d                # brings up API + worker + db + redis
```
Put **Caddy** or **nginx** in front for HTTPS, or a Google HTTPS load balancer.
This is closest to your current Docker Desktop setup — same compose file.

---

## Costs (rough, asia-south1, low traffic)

| Piece | Monthly |
|---|---|
| Cloud SQL db-custom-1-3840 | ~$50 (smallest usable pgvector) |
| Memorystore 1 GB | ~$35 |
| Cloud Run (min-instance 1, 2 vCPU) | ~$15–40 depending on traffic |
| **Total** | **~$100–125/mo** to start |

Option B on one `e2-standard-2` VM with self-hosted DB/Redis: **~$50/mo**, but
you own backups and uptime. Start on the VM to validate revenue, move to
Cloud Run + Cloud SQL when clients demand HA.

---

## Operational notes

- **Backups**: Cloud SQL has automated daily backups + point-in-time recovery —
  turn it on. On the VM, `pg_dump` on a cron to a GCS bucket.
- **Migrations**: run automatically on boot (`apply_schema`). No manual step.
- **Scaling**: Cloud Run autoscales the API; keep `DB_POOL_MAX × max-instances`
  under Cloud SQL's connection limit, or add **PgBouncer**.
- **Logs & metrics**: Cloud Run streams to Cloud Logging automatically; scrape
  `/metrics` (Prometheus format) with Managed Prometheus or Grafana Cloud.
- **Multilingual clients**: swap `LOCAL_EMBED_MODEL=BAAI/bge-m3` + `EMBED_DIM=1024`
  for strong non-English retrieval (one env change; re-index sites after).
- **Region**: `asia-south1` (Mumbai) for India/Razorpay latency; `us-central1`
  or `europe-west1` otherwise.
