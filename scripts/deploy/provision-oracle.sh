#!/usr/bin/env bash
# Provision a SiteBot VM on Oracle Cloud (OCI) using the Always Free Ampere A1
# shape. Run on YOUR machine with the OCI CLI installed and configured
# (`oci setup config`).
#
# OCI needs two OCIDs you get from the console (Compute is region+VCN specific):
#   COMPARTMENT_ID  your compartment OCID (Identity -> Compartments)
#   SUBNET_ID       a PUBLIC subnet OCID in a VCN (Networking -> VCN -> Subnets)
# The subnet's security list must allow ingress TCP 80 and 443 from 0.0.0.0/0.
#
#   COMPARTMENT_ID=ocid1.compartment... SUBNET_ID=ocid1.subnet... \
#     OCPUS=2 MEM_GB=12 ./provision-oracle.sh
set -euo pipefail
: "${COMPARTMENT_ID:?Set COMPARTMENT_ID (your compartment OCID)}"
: "${SUBNET_ID:?Set SUBNET_ID (a public subnet OCID)}"
NAME="${NAME:-sitebot-vm}"; OCPUS="${OCPUS:-2}"; MEM_GB="${MEM_GB:-12}"
SSH_KEY="${SSH_KEY:-$HOME/.ssh/id_ed25519.pub}"
command -v oci >/dev/null || { echo "Install the OCI CLI first."; exit 1; }
[ -f "$SSH_KEY" ] || { echo "No SSH public key at $SSH_KEY"; exit 1; }

echo "==> Finding an availability domain..."
AD=$(oci iam availability-domain list --compartment-id "$COMPARTMENT_ID" \
  --query 'data[0].name' --raw-output)

echo "==> Finding the latest Ubuntu 24.04 ARM (aarch64) image..."
IMG=$(oci compute image list --compartment-id "$COMPARTMENT_ID" \
  --operating-system "Canonical Ubuntu" --operating-system-version "24.04" \
  --shape "VM.Standard.A1.Flex" --sort-by TIMECREATED \
  --query 'data[0].id' --raw-output)

echo "==> Launching Always-Free Ampere A1 ($OCPUS OCPU / ${MEM_GB}GB)..."
oci compute instance launch \
  --compartment-id "$COMPARTMENT_ID" --availability-domain "$AD" \
  --display-name "$NAME" --shape "VM.Standard.A1.Flex" \
  --shape-config "{\"ocpus\": $OCPUS, \"memoryInGBs\": $MEM_GB}" \
  --image-id "$IMG" --subnet-id "$SUBNET_ID" \
  --assign-public-ip true \
  --ssh-authorized-keys-file "$SSH_KEY" \
  --wait-for-state RUNNING >/tmp/oci_launch.json

IID=$(oci compute instance list --compartment-id "$COMPARTMENT_ID" \
  --display-name "$NAME" --query 'data[0].id' --raw-output)
IP=$(oci compute instance list-vnics --instance-id "$IID" \
  --query 'data[0]."public-ip"' --raw-output)

cat <<EOF

✅ Instance ready. Public IP: $IP

Next:
  1. DNS: add an A record  bot.yourdomain.com -> $IP
  2. Confirm the subnet security list allows ingress TCP 80 and 443.
  3. SSH in:   ssh ubuntu@$IP
  4. IMPORTANT (OCI images block ports at the host firewall too) — on the VM:
       sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 80 -j ACCEPT
       sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 443 -j ACCEPT
       sudo netfilter-persistent save
  5. Run the one-command deploy:
       export SITEBOT_DOMAIN=bot.yourdomain.com
       export ANTHROPIC_API_KEY=sk-ant-...
       curl -fsSL https://raw.githubusercontent.com/ankitjha67/SiteBot/main/sitebot/scripts/deploy/setup-server.sh | bash
EOF
