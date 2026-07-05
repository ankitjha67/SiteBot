#!/usr/bin/env bash
# Provision a SiteBot VM on AWS Lightsail (simplest, fixed price). Run on YOUR
# machine with the AWS CLI installed and configured (`aws configure`).
#   NAME=sitebot REGION=ap-south-1 BUNDLE=medium_3_0 ./provision-aws.sh
# Bundles: small_3_0 (2GB ~$12), medium_3_0 (4GB ~$24, recommended).
set -euo pipefail
NAME="${NAME:-sitebot}"; REGION="${REGION:-ap-south-1}"; BUNDLE="${BUNDLE:-medium_3_0}"
command -v aws >/dev/null || { echo "Install the AWS CLI first."; exit 1; }

BP=$(aws lightsail get-blueprints --region "$REGION" \
  --query "blueprints[?contains(blueprintId,'ubuntu_24')].blueprintId | [0]" --output text)
: "${BP:=ubuntu_24_04}"

echo "==> Creating Lightsail instance $NAME in $REGION ($BUNDLE, $BP)..."
aws lightsail create-instances --region "$REGION" \
  --instance-names "$NAME" \
  --availability-zone "${REGION}a" \
  --blueprint-id "$BP" --bundle-id "$BUNDLE"

echo "==> Waiting for the instance to run..."
until [ "$(aws lightsail get-instance --region "$REGION" --instance-name "$NAME" \
  --query 'instance.state.name' --output text 2>/dev/null)" = "running" ]; do sleep 5; done

echo "==> Opening ports 80/443 (22 is open by default)..."
aws lightsail open-instance-public-ports --region "$REGION" --instance-name "$NAME" \
  --port-info fromPort=80,toPort=80,protocol=TCP
aws lightsail open-instance-public-ports --region "$REGION" --instance-name "$NAME" \
  --port-info fromPort=443,toPort=443,protocol=TCP

echo "==> Attaching a static IP..."
aws lightsail allocate-static-ip --region "$REGION" --static-ip-name "${NAME}-ip" 2>/dev/null || true
aws lightsail attach-static-ip --region "$REGION" --static-ip-name "${NAME}-ip" --instance-name "$NAME" 2>/dev/null || true
IP=$(aws lightsail get-static-ip --region "$REGION" --static-ip-name "${NAME}-ip" \
  --query 'staticIp.ipAddress' --output text)

cat <<EOF

✅ Instance ready. Public (static) IP: $IP

Next:
  1. DNS: add an A record  bot.yourdomain.com -> $IP
  2. Download the SSH key from the Lightsail console (Account -> SSH keys), then:
       ssh -i LightsailDefaultKey.pem ubuntu@$IP
  3. On the VM, run the one-command deploy:
       export SITEBOT_DOMAIN=bot.yourdomain.com
       export ANTHROPIC_API_KEY=sk-ant-...
       curl -fsSL https://raw.githubusercontent.com/ankitjha67/SiteBot/main/sitebot/scripts/deploy/setup-server.sh | bash
EOF
