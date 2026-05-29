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

# Copy updated scripts, config, api, and web
echo "Copying scripts..."
cp "$REPO_DIR"/scripts/*.py  "$CARMEN_DIR/scripts/"
cp "$REPO_DIR"/config/*.py   "$CARMEN_DIR/config/"
cp "$REPO_DIR"/web/*         "$CARMEN_DIR/web/"

# Copy API module
mkdir -p "$CARMEN_DIR/api"
cp "$REPO_DIR"/api/*.py "$CARMEN_DIR/api/"

# Update Python dependencies if requirements changed
echo "Checking Python dependencies..."
"$CARMEN_DIR/venv/bin/pip" install -r "$REPO_DIR/requirements.txt" -q

# Initialise filters.json if it doesn't exist yet
if [ ! -f "$CARMEN_DIR/filters.json" ]; then
    echo "Creating initial filters.json..."
    cd "$CARMEN_DIR"
    "$CARMEN_DIR/venv/bin/python" scripts/create_filters_json.py
fi

# Restart the API service if it's installed
if systemctl is-active --quiet carmen-api 2>/dev/null; then
    echo "Restarting carmen-api service..."
    systemctl restart carmen-api
    echo "  API service restarted."
else
    echo "  carmen-api service not running (skipping restart)."
fi

echo ""
echo "=== Update complete! ==="
echo "Scripts are live. Next run will use the updated code."
