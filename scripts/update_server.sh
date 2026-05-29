#!/bin/bash
# Carmen Briefing — deploy updated scripts to the server
# Run this on the Hetzner VPS whenever you push code changes to GitHub:
#
#   bash /opt/carmen/repo/scripts/update_server.sh

set -e

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
CARMEN_DIR="/opt/carmen"

echo "=== Carmen — Updating server scripts ==="

# Pull latest code from GitHub
echo "Pulling latest code..."
cd "$REPO_DIR"
git pull

# Copy updated scripts and config
echo "Copying scripts..."
cp "$REPO_DIR"/scripts/*.py "$CARMEN_DIR/scripts/"
cp "$REPO_DIR"/config/*.py  "$CARMEN_DIR/config/"
cp "$REPO_DIR"/web/*        "$CARMEN_DIR/web/"

# Update Python dependencies if requirements changed
echo "Checking Python dependencies..."
"$CARMEN_DIR/venv/bin/pip" install -r "$REPO_DIR/requirements.txt" -q

echo ""
echo "=== Update complete! ==="
echo "Scripts are live. Next run will use the updated code."
