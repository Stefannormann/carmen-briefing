"""
Generate Carmen's spoken script via Gemini, using scored geo and market stories.
Saves full script to tmp/script.txt and segment list to tmp/segments.json.

Usage:
    python scripts/generate_script.py [--dry-run]
"""

import argparse
import json
import os
import sys
import time
from datetime import date
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent.parent))
from scripts.watchlist import prioritise_stories

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"

TMP_DIR = Path("tmp")
SCRIPT_FILE = TMP_DIR / "script.txt"
SEGMENTS_FILE = TMP_DIR / "segments.json"
GEO_FILE = TMP_DIR / "geo_stories.json"
MARKET_FILE = TMP_DIR / "market_stories.json"

TRANSITION_MARKER = "---TRANSITION---"

SYSTEM_PROMPT = """\
You are a professional radio script writer for a daily morning news briefing podcast.
The host is Carmen — a warm, engaging, professional female journalist who speaks
directly to the listener as if on a morning radio show.
Her tone is confident but approachable. She does not read bullet points —
she speaks in natural, flowing, broadcaster sentences.

Write the complete spoken script for today's episode.
Do NOT include stage directions, sound cues, or production notes.
Write only Carmen's spoken words.

STRUCTURE:

1. INTRO (~30 seconds)
   Carmen greets the listener and previews today's 2–3 top stories in one
   sentence each. Warm and energising.

2. GEOPOLITICAL SEGMENT (~4–6 minutes, 2–3 stories)
   For each story, Carmen covers three things in order:
   - What happened (facts, briefly)
   - Why it matters geopolitically (analysis and context)
   - What to watch next (forward-looking signal)
   Each story should be approximately 2 minutes of spoken audio (~280 words).
   If a story has watchlist_flag = true, Carmen adds one bridging sentence at
   the end of that story noting the company relevance (use watchlist_note).
   Separate stories with exactly: ---TRANSITION---

3. MARKETS SEGMENT (~4 minutes)
   Carmen presents company news in the priority order provided.
   No prices or numbers — news and developments only.
   Separate stories with exactly: ---TRANSITION---

4. CLOSING (~30 seconds)
   Carmen signs off warmly and mentions tomorrow's briefing.
"""


def gemini_call(prompt: str, dry_run: bool = False) -> str:
    if dry_run:
        print(f"[DRY-RUN] Gemini prompt ({len(prompt)} chars):\n{prompt[:500]}…\n")
        # Return a minimal placeholder script for dry-run testing
        return (
            "Good morning! I'm Carmen, and here's your briefing for today.\n"
            f"Today is {date.today().strftime('%A, %d %B %Y')}.\n\n"
            f"{TRANSITION_MARKER}\n\n"
            "In geopolitical news, this is a dry-run placeholder story. "
            "Nothing to report today — but in a real run, Gemini would craft a "
            "full two-minute analysis here.\n\n"
            f"{TRANSITION_MARKER}\n\n"
            "On the markets front, your watchlist companies have been active. "
            "This is a placeholder — real stories would appear in a live run.\n\n"
            f"{TRANSITION_MARKER}\n\n"
            "That's all for today's Carmen Briefing. Tune in tomorrow for your next update. "
            "Have a great day!"
        )
    if not GEMINI_API_KEY:
        print("ERROR: GEMINI_API_KEY not set.", file=sys.stderr)
        sys.exit(1)
    payload = {
        "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.7,
            "maxOutputTokens": 8192,
        },
    }
    retries = 4
    for attempt in range(1, retries + 1):
        try:
            resp = requests.post(
                GEMINI_URL,
                params={"key": GEMINI_API_KEY},
                json=payload,
                timeout=120,
            )
            if resp.status_code in (429, 503, 529) and attempt < retries:
                wait = 10 * attempt
                print(f"  Gemini {resp.status_code} — retrying in {wait}s (attempt {attempt}/{retries})…")
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp.json()["candidates"][0]["content"]["parts"][0]["text"]
        except requests.exceptions.ReadTimeout:
            if attempt < retries:
                wait = 15 * attempt
                print(f"  Gemini timeout — retrying in {wait}s (attempt {attempt}/{retries})…")
                time.sleep(wait)
            else:
                raise
    raise RuntimeError("Gemini call failed after all retries")


def load_json(path: Path, label: str) -> list:
    if not path.exists():
        print(f"ERROR: {label} file not found: {path}", file=sys.stderr)
        print("       Run fetch_geo_news.py and fetch_market_news.py first.", file=sys.stderr)
        sys.exit(1)
    with path.open() as f:
        return json.load(f)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    TMP_DIR.mkdir(exist_ok=True)

    geo_stories = load_json(GEO_FILE, "geo_stories")
    market_stories = load_json(MARKET_FILE, "market_stories")

    # Apply watchlist prioritisation and cap to top 15 companies
    # (39 companies is too many for a 4-minute segment)
    market_stories = prioritise_stories(market_stories)[:15]
    print(f"Using {len(geo_stories)} geo stories and {len(market_stories)} market stories.")

    today = date.today().strftime("%A, %d %B %Y")

    prompt = (
        f"Today's date: {today}\n\n"
        "GEOPOLITICAL STORIES (in selected order, present in this sequence):\n"
        + json.dumps(geo_stories, indent=2, ensure_ascii=False)
        + "\n\nCOMPANY NEWS (in priority order, present in this sequence):\n"
        + json.dumps(market_stories, indent=2, ensure_ascii=False)
    )

    print("Generating Carmen's script via Gemini…")
    script = gemini_call(prompt, args.dry_run)

    SCRIPT_FILE.write_text(script, encoding="utf-8")
    print(f"Script saved → {SCRIPT_FILE} ({len(script)} chars)")

    # Split on transition markers
    segments = [s.strip() for s in script.split(TRANSITION_MARKER) if s.strip()]
    SEGMENTS_FILE.write_text(json.dumps(segments, indent=2, ensure_ascii=False))
    print(f"Segments saved → {SEGMENTS_FILE} ({len(segments)} segments)")

    if args.dry_run:
        print("\n[DRY-RUN] Segments preview:")
        for i, seg in enumerate(segments):
            print(f"  Segment {i:02d}: {seg[:80]}…")


if __name__ == "__main__":
    main()
