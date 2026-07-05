#!/usr/bin/env bash
# Provision a SiteBot VM on Google Cloud (Compute Engine). Run on YOUR machine
# with gcloud installed and authed (`gcloud auth login`).
#   NAME=sitebot-vm ZONE=asia-south1-a MACHINE=e2-standard-2 ./provision-gcp.sh
set -euo pipefail
NAME="${NAME:-sitebot-vm}"; ZONE="${ZONE:-asia-south1-a}"; MACHINE="${MACHINE:-e2-standard-2}"
command -v gcloud >/dev/null || { echo "Install the gcloud CLI first."; exit 1; }

echo "==> Creating VM $NAME in $ZONE ($MACHINE)..."
gcloud compute instances create "$NAME" \
  --zone="$ZONE" --machine-type="$MACHINE" \
  --image-family=ubuntu-2404-lts --image-project=ubuntu-os-cloud \
  --boot-disk-size=30GB --tags=http-server,https-server

echo "==> Opening ports 80/443..."
gcloud compute firewall-rules create sitebot-allow-web \
  --allow=tcp:80,tcp:443 --target-tags=http-server,https-server 2>/dev/null \
  || echo "   (firewall rule already exists)"

IP=$(gcloud compute instances describe "$NAME" --zone="$ZONE" \
  --format='get(networkInterfaces[0].accessConfigs[0].natIP)')
cat <<EOF

✅ VM ready. Public IP: $IP

Next:
  1. DNS: add an A record  bot.yourdomain.com -> $IP
  2. SSH in:   gcloud compute ssh $NAME --zone=$ZONE
  3. On the VM, run the one-command deploy:
       export SITEBOT_DOMAIN=bot.yourdomain.com
       export ANTHROPIC_API_KEY=sk-ant-...
       curl -fsSL https://raw.githubusercontent.com/ankitjha67/SiteBot/main/sitebot/scripts/deploy/setup-server.sh | bash
EOF
