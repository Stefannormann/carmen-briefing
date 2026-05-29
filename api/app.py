"""
Carmen Briefing — REST API
Runs on 127.0.0.1:5000, proxied by nginx at /api/

Endpoints (all return JSON):
  GET  /api/health              — liveness check (no auth)
  GET  /api/episodes            — episode list from index.json (no auth)
  GET  /api/episodes/<date>     — episode detail sidecar (no auth)
  GET  /api/filters             — current filters.json (Bearer token required)
  PUT  /api/filters             — replace filters.json (Bearer token required)

Auth:
  Set CARMEN_API_TOKEN in /opt/carmen/.env  (generated with `openssl rand -hex 32`)
  Pass as:  Authorization: Bearer <token>

Usage (server):
  source venv/bin/activate
  gunicorn -w 1 -b 127.0.0.1:5000 api.app:app --chdir /opt/carmen
  # Or run via systemd: see scripts/setup_server.sh notes
"""

import json
import os
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path

from flask import Flask, Response, abort, jsonify, request

app = Flask(__name__)
app.config["JSON_SORT_KEYS"] = False

# ── Paths ─────────────────────────────────────────────────────────────────────
_BASE = Path(os.environ.get("CARMEN_DIR", "/opt/carmen"))
EPISODES_DIR  = _BASE / "episodes"
FILTERS_FILE  = _BASE / "filters.json"
API_TOKEN     = os.environ.get("CARMEN_API_TOKEN", "")


# ── Auth helper ───────────────────────────────────────────────────────────────

def require_auth(f):
    """Decorator: require valid Bearer token."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not API_TOKEN:
            abort(503, description="CARMEN_API_TOKEN not configured on server.")
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer ") or auth[7:] != API_TOKEN:
            abort(401, description="Invalid or missing Bearer token.")
        return f(*args, **kwargs)
    return decorated


# ── CORS helper (allow PWA origin) ────────────────────────────────────────────

def _cors(response: Response) -> Response:
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type"
    response.headers["Access-Control-Allow-Methods"] = "GET, PUT, OPTIONS"
    return response


@app.after_request
def after_request(response):
    return _cors(response)


@app.route("/api/health", methods=["GET", "OPTIONS"])
def health():
    return jsonify({
        "status": "ok",
        "time":   datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    })


# ── Episodes ──────────────────────────────────────────────────────────────────

@app.route("/api/episodes", methods=["GET"])
def list_episodes():
    index_file = EPISODES_DIR / "index.json"
    if not index_file.exists():
        return jsonify([])
    try:
        return app.response_class(
            response=index_file.read_text(encoding="utf-8"),
            mimetype="application/json",
        )
    except Exception as e:
        abort(500, description=str(e))


@app.route("/api/episodes/<date_str>", methods=["GET"])
def get_episode(date_str: str):
    # Basic validation to prevent path traversal
    if not date_str.replace("-", "").isdigit() or len(date_str) != 10:
        abort(400, description="date must be YYYY-MM-DD")
    meta_file = EPISODES_DIR / f"{date_str}.json"
    if not meta_file.exists():
        abort(404, description=f"No metadata for {date_str}")
    return app.response_class(
        response=meta_file.read_text(encoding="utf-8"),
        mimetype="application/json",
    )


# ── Filters (auth required) ───────────────────────────────────────────────────

@app.route("/api/filters", methods=["GET", "OPTIONS"])
@require_auth
def get_filters():
    if not FILTERS_FILE.exists():
        abort(404, description="filters.json not found — run create_filters_json.py first.")
    return app.response_class(
        response=FILTERS_FILE.read_text(encoding="utf-8"),
        mimetype="application/json",
    )


@app.route("/api/filters", methods=["PUT"])
@require_auth
def update_filters():
    data = request.get_json(force=True, silent=True)
    if not data:
        abort(400, description="Request body must be valid JSON.")

    required_keys = {"geo_sources", "geo_keywords", "companies"}
    missing = required_keys - set(data.keys())
    if missing:
        abort(400, description=f"Missing required keys: {', '.join(sorted(missing))}")

    data["version"]    = data.get("version", 1)
    data["updated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    FILTERS_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return jsonify({"status": "ok", "updated_at": data["updated_at"]})


# ── Error handlers ────────────────────────────────────────────────────────────

@app.errorhandler(400)
@app.errorhandler(401)
@app.errorhandler(404)
@app.errorhandler(500)
@app.errorhandler(503)
def handle_error(e):
    return jsonify({"error": e.name, "message": e.description}), e.code


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5001, debug=False)
