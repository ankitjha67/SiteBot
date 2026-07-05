#!/usr/bin/env bash
# One-command SiteBot deploy — run this ON a fresh Ubuntu VM (any cloud).
# It installs Docker, fetches the code, writes a .env with strong random
# secrets, and launches the production stack with automatic HTTPS.
#
# Usage (minimum):
#   export SITEBOT_DOMAIN=bot.yourdomain.com
#   export ANTHROPIC_API_KEY=sk-ant-...          # or GEMINI_API_KEY / OPENAI_API_KEY
#   curl -fsSL https://raw.githubusercontent.com/ankitjha67/SiteBot/main/sitebot/scripts/deploy/setup-server.sh | bash
#
# Optional env: ANSWER_PROVIDER (anthropic|gemini|openai|openai_compatible),
#   ANSWER_MODEL, RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET, BILLING_CURRENCY.
set -euo pipefail

: "${SITEBOT_DOMAIN:?Set SITEBOT_DOMAIN (e.g. bot.yourdomain.com) before running}"
REPO_DIR="${REPO_DIR:-$HOME/SiteBot}"
PROVIDER="${ANSWER_PROVIDER:-anthropic}"

log() { printf '\n\033[1;32m==>\033[0m %s\n' "$*"; }

# --- Docker ---
if ! command -v docker >/dev/null 2>&1; then
  log "Installing Docker..."
  curl -fsSL https://get.docker.com | sh
fi
DC="docker compose"
docker compose version >/dev/null 2>&1 || DC="sudo docker compose"

# --- Code ---
if [ ! -d "$REPO_DIR/.git" ]; then
  log "Cloning SiteBot into $REPO_DIR..."
  git clone https://github.com/ankitjha67/SiteBot.git "$REPO_DIR"
fi
cd "$REPO_DIR/sitebot"

# --- .env (generate once; never overwrite existing secrets) ---
if [ ! -f .env ]; then
  log "Generating .env with strong random secrets..."
  ADMIN_KEY=$(openssl rand -base64 32)
  ENC_KEY=$(openssl rand -base64 32)
  PG_PW=$(openssl rand -base64 24 | tr -d '/+=')
  {
    echo "SITEBOT_DOMAIN=$SITEBOT_DOMAIN"
    echo "ADMIN_API_KEY=$ADMIN_KEY"
    echo "SECRET_ENCRYPTION_KEY=$ENC_KEY"
    echo "POSTGRES_PASSWORD=$PG_PW"
    echo "ANSWER_PROVIDER=$PROVIDER"
    echo "ANSWER_MODEL=${ANSWER_MODEL:-claude-haiku-4-5}"
    echo "ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY:-}"
    echo "GEMINI_API_KEY=${GEMINI_API_KEY:-}"
    echo "OPENAI_API_KEY=${OPENAI_API_KEY:-}"
    echo "OPENAI_COMPATIBLE_BASE_URL=${OPENAI_COMPATIBLE_BASE_URL:-}"
    echo "EMBED_PROVIDER=local"
    echo "EMBED_DIM=384"
    echo "RERANK_ENABLED=true"
    echo "RAZORPAY_KEY_ID=${RAZORPAY_KEY_ID:-}"
    echo "RAZORPAY_KEY_SECRET=${RAZORPAY_KEY_SECRET:-}"
    echo "RAZORPAY_WEBHOOK_SECRET=${RAZORPAY_WEBHOOK_SECRET:-}"
    echo "BILLING_CURRENCY=${BILLING_CURRENCY:-inr}"
  } > .env
  echo
  echo "  Your ADMIN key (log in to the dashboard with this — save it now):"
  echo "  $ADMIN_KEY"
  echo
else
  log ".env already exists — leaving it untouched."
fi

# --- Launch ---
log "Building and starting the stack (this pulls images + builds; first run ~2-4 min)..."
$DC -f docker-compose.prod.yml up -d --build

log "Waiting for HTTPS + health at https://$SITEBOT_DOMAIN ..."
for i in $(seq 1 40); do
  if curl -fsS "https://$SITEBOT_DOMAIN/healthz" >/dev/null 2>&1; then
    log "LIVE ✅  Console: https://$SITEBOT_DOMAIN/dashboard   Onboarding: https://$SITEBOT_DOMAIN/onboarding"
    exit 0
  fi
  sleep 6
done
echo
echo "Not healthy yet. Check:"
echo "  - DNS: does $SITEBOT_DOMAIN resolve to this server's IP?  (dig +short $SITEBOT_DOMAIN)"
echo "  - Firewall: are ports 80 AND 443 open? (cloud security group + on Oracle also the VM iptables)"
echo "  - Logs: $DC -f docker-compose.prod.yml logs caddy api"
exit 1
