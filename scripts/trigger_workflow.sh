#!/bin/bash
# Backup trigger for Carmen daily briefing workflow.
# Run this as a cron job on the VPS to ensure the workflow fires even if
# GitHub's own scheduler misses it.
#
# SETUP:
#   1. Create a GitHub Personal Access Token (PAT):
#      GitHub → Settings → Developer settings → Personal access tokens → Tokens (classic)
#      Scopes required: workflow
#   2. Store the token on the VPS:
#      echo "YOUR_TOKEN_HERE" > /root/.carmen_github_token
#      chmod 600 /root/.carmen_github_token
#   3. Add to VPS crontab (run: crontab -e):
#      0 5 * * * /root/trigger_workflow.sh >> /var/log/carmen_trigger.log 2>&1
#      (05:00 UTC = 07:00 CEST)
#
# The script is idempotent — if GitHub already ran the scheduled workflow,
# triggering it again just creates a second run which will commit "nothing to commit".

REPO="Stefannormann/carmen-briefing"
WORKFLOW="daily_briefing.yml"
TOKEN_FILE="/root/.carmen_github_token"

if [ ! -f "$TOKEN_FILE" ]; then
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] ERROR: Token file not found: $TOKEN_FILE"
    exit 1
fi

TOKEN=$(cat "$TOKEN_FILE")

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Triggering Carmen workflow…"

HTTP_STATUS=$(curl -s -o /tmp/carmen_trigger_response.json -w "%{http_code}" \
    -X POST \
    -H "Authorization: token $TOKEN" \
    -H "Accept: application/vnd.github.v3+json" \
    "https://api.github.com/repos/$REPO/actions/workflows/$WORKFLOW/dispatches" \
    -d '{"ref":"main"}')

if [ "$HTTP_STATUS" = "204" ]; then
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] SUCCESS: Workflow triggered (HTTP 204)."
else
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] ERROR: HTTP $HTTP_STATUS"
    cat /tmp/carmen_trigger_response.json
    exit 1
fi
