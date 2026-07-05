#!/usr/bin/env bash
# Provision a SiteBot VM on Microsoft Azure. Run on YOUR machine with the Azure
# CLI installed and authed (`az login`).
#   RG=sitebot-rg NAME=sitebot-vm LOCATION=centralindia SIZE=Standard_B2s ./provision-azure.sh
set -euo pipefail
RG="${RG:-sitebot-rg}"; NAME="${NAME:-sitebot-vm}"
LOCATION="${LOCATION:-centralindia}"; SIZE="${SIZE:-Standard_B2s}"
SSH_KEY="${SSH_KEY:-$HOME/.ssh/id_ed25519.pub}"
command -v az >/dev/null || { echo "Install the Azure CLI first."; exit 1; }
[ -f "$SSH_KEY" ] || { echo "No SSH public key at $SSH_KEY (run: ssh-keygen -t ed25519)"; exit 1; }

echo "==> Resource group $RG in $LOCATION..."
az group create --name "$RG" --location "$LOCATION" -o none

echo "==> Creating VM $NAME ($SIZE)..."
az vm create --resource-group "$RG" --name "$NAME" \
  --image Ubuntu2404 --size "$SIZE" \
  --admin-username azureuser --ssh-key-values "$SSH_KEY" \
  --public-ip-sku Standard -o none

echo "==> Opening ports 80/443..."
az vm open-port --resource-group "$RG" --name "$NAME" --port 80 --priority 900 -o none
az vm open-port --resource-group "$RG" --name "$NAME" --port 443 --priority 901 -o none

IP=$(az vm show -d -g "$RG" -n "$NAME" --query publicIps -o tsv)
cat <<EOF

✅ VM ready. Public IP: $IP

Next:
  1. DNS: add an A record  bot.yourdomain.com -> $IP
  2. SSH in:   ssh azureuser@$IP
  3. On the VM, run the one-command deploy:
       export SITEBOT_DOMAIN=bot.yourdomain.com
       export ANTHROPIC_API_KEY=sk-ant-...
       curl -fsSL https://raw.githubusercontent.com/ankitjha67/SiteBot/main/sitebot/scripts/deploy/setup-server.sh | bash
EOF
