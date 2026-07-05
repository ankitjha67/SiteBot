# One-command SiteBot deployment scripts

Two steps: **provision a VM** on your cloud (run on your machine), then run the
**one-command deploy** on that VM. Full walkthrough: `docs/DEPLOYMENT.md`.

## Step 1 — provision a VM (run locally, cloud CLI required)

| Cloud | Command | Notes |
|-------|---------|-------|
| GCP | `./provision-gcp.sh` | needs `gcloud` authed |
| AWS | `./provision-aws.sh` | Lightsail; needs `aws` configured |
| Azure | `./provision-azure.sh` | needs `az login` |
| Oracle | `COMPARTMENT_ID=... SUBNET_ID=... ./provision-oracle.sh` | Always-Free Ampere A1; needs two OCIDs from the console |

Each prints the VM's public IP and the exact next commands. Override defaults
with env vars, e.g. `ZONE=us-central1-a MACHINE=e2-standard-2 ./provision-gcp.sh`.

## Step 2 — point DNS, then deploy (run on the VM)

Add a DNS **A record** `bot.yourdomain.com -> <the VM IP>`, SSH in, then:

```bash
export SITEBOT_DOMAIN=bot.yourdomain.com
export ANTHROPIC_API_KEY=sk-ant-...     # or GEMINI_API_KEY / OPENAI_API_KEY
curl -fsSL https://raw.githubusercontent.com/ankitjha67/SiteBot/main/sitebot/scripts/deploy/setup-server.sh | bash
```

`setup-server.sh` installs Docker, generates a `.env` with strong random
secrets (and prints your admin key once), and launches the stack with automatic
HTTPS via Caddy. When it finishes you get:

- Console: `https://bot.yourdomain.com/dashboard`
- Onboarding: `https://bot.yourdomain.com/onboarding`

It's safe to re-run — it won't overwrite an existing `.env`.
