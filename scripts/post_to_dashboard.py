"""
Post today's briefing data to the family dashboard API.
Called from run_briefing.sh as the final step after manage_archive.py.

Reads:  episodes/index.json  (date, filename, duration)
        tmp/episode_metadata.json  (geo + market story headlines)
Posts:  briefing_date, audio_url, duration_seconds, headlines
        → https://dash.stefannormann.com/api/news

Environment variables required:
    DASHBOARD_API_KEY   — matches NEWS_API_KEY in the dashboard .env

A failure here logs a warning but does NOT abort the briefing pipeline.

Usage:
    python scripts/post_to_dashboard.py [--dry-run]
"""

import argparse
import json
import os
import sys
from pathlib import Path

import requests

DASHBOARD_URL = "https://dash.stefannormann.com/api/news"
EPISODES_DIR  = Path("episodes")
TMP_DIR       = Path("tmp")

# How many market story items to include as headline bullets (after geo stories)
MAX_MARKET_HEADLINES = 3


def build_headlines(meta: dict) -> list[str]:
    """Extract human-readable headline strings from episode metadata."""
    headlines = []

    for s in meta.get("geo_stories", []):
        h = (s.get("headline") or "").strip()
        if h:
            headlines.append(h)

    for s in meta.get("market_stories", [])[:MAX_MARKET_HEADLINES]:
        name = (s.get("name") or s.get("ticker") or "").strip()
        h    = (s.get("headline") or "").strip()
        if name and h:
            # Trim long headlines so they fit as bullets
            h_short = h if len(h) <= 90 else h[:87] + "…"
            headlines.append(f"{name}: {h_short}")
        elif h:
            headlines.append(h[:90])

    return headlines


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="Print payload without sending")
    args = parser.parse_args()

    api_key = os.environ.get("DASHBOARD_API_KEY", "")
    if not api_key and not args.dry_run:
        print("WARN: DASHBOARD_API_KEY not set — skipping dashboard post.", file=sys.stderr)
        return

    # ── Load latest episode ───────────────────────────────────────────────────
    index_file = EPISODES_DIR / "index.json"
    if not index_file.exists():
        print("WARN: episodes/index.json not found — skipping dashboard post.", file=sys.stderr)
        return

    try:
        episodes = json.loads(index_file.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"WARN: Could not read index.json: {e}", file=sys.stderr)
        return

    if not episodes:
        print("WARN: No episodes in index — skipping dashboard post.", file=sys.stderr)
        return

    latest   = episodes[0]   # index is newest-first
    date_str = latest["date"]
    audio_url = f"https://carmen.stefannormann.com/episodes/{latest['filename']}"
    duration  = latest.get("duration_seconds") or 0

    # ── Build headlines ───────────────────────────────────────────────────────
    headlines: list[str] = []
    meta_file = TMP_DIR / "episode_metadata.json"
    if meta_file.exists():
        try:
            meta      = json.loads(meta_file.read_text(encoding="utf-8"))
            headlines = build_headlines(meta)
        except Exception as e:
            print(f"WARN: Could not read episode_metadata.json: {e}", file=sys.stderr)

    if not headlines:
        # Fallback: use episode title as the single headline
        headlines = [latest.get("title", f"Carmen Briefing — {date_str}")]

    # ── Assemble payload ──────────────────────────────────────────────────────
    payload = {
        "briefing_date":    date_str,
        "audio_url":        audio_url,
        "duration_seconds": duration,
        "headlines":        headlines,
    }

    if args.dry_run:
        print("[DRY-RUN] Would POST to:", DASHBOARD_URL)
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return

    # ── POST ──────────────────────────────────────────────────────────────────
    try:
        resp = requests.post(
            DASHBOARD_URL,
            headers={
                "x-api-key":    api_key,
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=15,
        )
        resp.raise_for_status()
        result = resp.json()
        print(
            f"Dashboard updated: {date_str} | "
            f"{len(headlines)} headlines | "
            f"{duration}s | {result}"
        )
    except requests.exceptions.HTTPError as e:
        print(f"WARN: Dashboard POST failed ({e.response.status_code}): {e}", file=sys.stderr)
    except Exception as e:
        print(f"WARN: Dashboard POST failed: {e}", file=sys.stderr)
    # Never sys.exit — dashboard failure must not abort the briefing pipeline


if __name__ == "__main__":
    main()
