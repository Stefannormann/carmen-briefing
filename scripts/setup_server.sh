#!/bin/bash
# Carmen Briefing — one-time server setup script
# Run as root on the Hetzner VPS after cloning the repo:
#
#   git clone https://github.com/Stefannormann/carmen-briefing.git /opt/carmen/repo
#   bash /opt/carmen/repo/scripts/setup_server.sh

set -e

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
CARMEN_DIR="/opt/carmen"

echo "============================================="
echo " Carmen Briefing — Server Setup"
echo "============================================="
echo " Repo:    $REPO_DIR"
echo " Install: $CARMEN_DIR"
echo ""

# ── 1. Directory structure ────────────────────────────────────────────────────
echo "[1/9] Creating directory structure..."
mkdir -p "$CARMEN_DIR"/{scripts,config,api,audio,episodes,web,logs,tmp}

# ── 2. Copy files from repo ───────────────────────────────────────────────────
echo "[2/9] Copying scripts and web files from repo..."
cp "$REPO_DIR"/scripts/*.py  "$CARMEN_DIR/scripts/"
cp "$REPO_DIR"/config/*.py   "$CARMEN_DIR/config/"
cp "$REPO_DIR"/api/*.py      "$CARMEN_DIR/api/"
cp "$REPO_DIR"/web/*         "$CARMEN_DIR/web/"
cp "$REPO_DIR/requirements.txt" "$CARMEN_DIR/"

# ── 3. System dependencies ────────────────────────────────────────────────────
echo "[3/9] Installing ffmpeg..."
apt-get install -y ffmpeg -qq
echo "    ffmpeg ready."

# ── 4. Python virtual environment ────────────────────────────────────────────
echo "[4/9] Creating Python virtual environment..."
python3 -m venv "$CARMEN_DIR/venv"
"$CARMEN_DIR/venv/bin/pip" install --upgrade pip -q
"$CARMEN_DIR/venv/bin/pip" install -r "$CARMEN_DIR/requirements.txt" -q
echo "    Python dependencies installed."

# ── 5. Download audio assets ──────────────────────────────────────────────────
echo "[5/9] Downloading audio assets (jingle + transition)..."
cd "$CARMEN_DIR"
"$CARMEN_DIR/venv/bin/python" scripts/download_audio_assets.py

# ── 6. Create .env file ───────────────────────────────────────────────────────
echo "[6/9] Setting up environment file..."
if [ ! -f "$CARMEN_DIR/.env" ]; then
    cat > "$CARMEN_DIR/.env" << ENVEOF
GEMINI_API_KEY=REPLACE_WITH_YOUR_KEY
OPENAI_API_KEY=REPLACE_WITH_YOUR_KEY
CARMEN_API_TOKEN=$(openssl rand -hex 32)
ENVEOF
    chmod 600 "$CARMEN_DIR/.env"
    echo "    Created $CARMEN_DIR/.env"
    echo "    *** You must add your GEMINI_API_KEY before running! ***"
else
    echo "    .env already exists — skipping."
fi

# ── 7. Initialise filters.json + carmen-api service ──────────────────────────
echo "[7/9] Setting up the filters REST API..."
if [ ! -f "$CARMEN_DIR/filters.json" ]; then
    "$CARMEN_DIR/venv/bin/python" scripts/create_filters_json.py
fi
cp "$REPO_DIR/scripts/carmen-api.service" /etc/systemd/system/carmen-api.service
systemctl daemon-reload
systemctl enable --now carmen-api
echo "    carmen-api service installed and started."

# ── 8. Create run_briefing.sh ─────────────────────────────────────────────────
echo "[8/9] Creating daily run script..."
cat > "$CARMEN_DIR/run_briefing.sh" << 'RUNEOF'
#!/bin/bash
set -e

LOG="/opt/carmen/logs/$(date +%Y-%m-%d).log"
echo "=== Carmen started: $(date) ===" >> "$LOG"

cd /opt/carmen
source venv/bin/activate
set -a; source .env; set +a

# Re-download audio assets if somehow missing
if [ ! -f audio/jingle.mp3 ]; then
    echo "Audio assets missing — downloading..." >> "$LOG"
    python scripts/download_audio_assets.py >> "$LOG" 2>&1
fi

python scripts/fetch_geo_news.py    >> "$LOG" 2>&1
python scripts/fetch_market_news.py >> "$LOG" 2>&1
python scripts/generate_script.py   >> "$LOG" 2>&1
python scripts/synthesise_audio.py  >> "$LOG" 2>&1
python scripts/stitch_audio.py      >> "$LOG" 2>&1
python scripts/manage_archive.py    >> "$LOG" 2>&1

echo "=== Carmen completed: $(date) ===" >> "$LOG"
RUNEOF
chmod +x "$CARMEN_DIR/run_briefing.sh"
echo "    Run script created."

# ── 9. nginx configuration ────────────────────────────────────────────────────
echo "[9/9] Configuring nginx on port 8080..."
cat > /etc/nginx/sites-available/carmen << 'NGINXEOF'
server {
    listen 8080;
    server_name _;

    root /opt/carmen;

    # PWA web app
    location /web/ {
        try_files $uri $uri/ =404;
        add_header Cache-Control "no-cache";
    }

    # Episode MP3s and index.json
    location /episodes/ {
        try_files $uri =404;
        add_header Cache-Control "public, max-age=86400";
        add_header Accept-Ranges bytes;
    }

    # REST API (filters.json read/write) — proxied to gunicorn/carmen-api.service
    location /api/ {
        proxy_pass http://127.0.0.1:5001/api/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # Redirect root to web app
    location = / {
        return 301 /web/;
    }
}
NGINXEOF

if [ ! -L /etc/nginx/sites-enabled/carmen ]; then
    ln -s /etc/nginx/sites-available/carmen /etc/nginx/sites-enabled/carmen
fi

nginx -t && systemctl reload nginx
echo "    nginx configured and reloaded."

# ── Timezone ──────────────────────────────────────────────────────────────────
timedatectl set-timezone Europe/Helsinki
echo "    Timezone set to Europe/Helsinki."

# ── Log rotation ──────────────────────────────────────────────────────────────
# Keep 30 days of logs, clean up older ones daily
(crontab -l 2>/dev/null; echo "0 8 * * * find /opt/carmen/logs/ -name '*.log' -mtime +30 -delete") | sort -u | crontab -

echo ""
echo "============================================="
echo " Setup complete!"
echo "============================================="
echo ""
echo " NEXT STEPS (in order):"
echo ""
echo " 1. Add your Gemini API key:"
echo "    nano /opt/carmen/.env"
echo ""
echo " 2. Add the daily cron jobs:"
echo "    crontab -e"
echo "    Add these lines (server is Europe/Helsinki = EEST = UTC+3):"
echo "    # Main run: 07:00 EEST = 06:00 CEST (Denmark local time), Mon–Fri only"
echo "    0 7 * * 1-5 /opt/carmen/run_briefing.sh"
echo "    # Catch-up: 09:00 EEST (08:00 Denmark), Mon–Fri, only if episode is missing"
echo "    0 9 * * 1-5 [ -f /opt/carmen/episodes/\$(date +\%Y-\%m-\%d).mp3 ] || /opt/carmen/run_briefing.sh"
echo ""
echo " 3. Run a manual test:"
echo "    /opt/carmen/run_briefing.sh"
echo ""
echo " 4. Watch the log:"
echo "    tail -f /opt/carmen/logs/$(date +%Y-%m-%d).log"
echo ""
echo " 5. Open the web app:"
echo "    http://62.238.43.201:8080/web/"
echo ""
echo " 6. Your Content Filters API token (needed in the web app's Settings ->"
echo "    Content Filters panel to edit sources/buzzwords/watchlist):"
echo "    grep CARMEN_API_TOKEN /opt/carmen/.env"
echo "============================================="
