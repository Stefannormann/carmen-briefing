#!/bin/bash
# Deploy code changes from local repo to Hetzner VPS.
# Run from the project root after committing local changes.
#
# Usage:
#   bash scripts/deploy.sh
#
# What it does:
#   1. git push origin main
#   2. SSH to VPS: git pull + copy scripts/config/web + pip install + restart API

set -e

VPS_HOST="root@62.238.43.201"
VPS_KEY="$HOME/.ssh/4a_dashboard_vps"

echo "=== Carmen Briefing — Deploy ==="
echo ""

echo "[1/2] Pushing to GitHub..."
git push origin main
echo "      Done."
echo ""

echo "[2/2] Deploying to VPS..."
ssh -i "$VPS_KEY" "$VPS_HOST" "bash /opt/carmen/repo/scripts/update_server.sh"
echo ""

echo "=== Deploy complete! ==="
echo "    Code is live at carmen.stefannormann.com"
