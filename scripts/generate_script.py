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

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_URL = "https://api.openai.com/v1/chat/completions"
OPENAI_MODEL = "gpt-4o-mini"

TMP_DIR = Path("tmp")
SCRIPT_FILE       = TMP_DIR / "script.txt"
SEGMENTS_FILE     = TMP_DIR / "segments.json"
STRATEGIC_FILE    = TMP_DIR / "strategic_stories.json"
TECH_FILE         = TMP_DIR / "tech_stories.json"
GEO_FILE          = TMP_DIR / "geo_stories.json"   # backward-compat fallback
MARKET_FILE       = TMP_DIR / "market_stories.json"
METADATA_FILE     = TMP_DIR / "episode_metadata.json"

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
   Carmen greets the listener and briefly previews one headline from each of the
   three segments. Warm and energising.

2. GLOBAL STRATEGIC AFFAIRS (~3–5 minutes, 2–3 stories)
   For each story, Carmen covers three things in order:
   - What happened (facts, briefly)
   - Why it matters strategically or geopolitically (analysis and context)
   - What to watch next (forward-looking signal)
   Each story should be approximately 90–120 seconds of spoken audio (~200 words).
   If a story has watchlist_flag = true, Carmen adds one bridging sentence at
   the end of that story noting the company relevance (use watchlist_note).
   Separate stories with exactly: ---TRANSITION---

3. AI & TECH (~3–5 minutes, 2–3 stories)
   Same format as segment 2 — what happened, why it matters, what to watch.
   Focus on the strategic and practical significance of each development,
   not just the technical details.
   If a story has watchlist_flag = true, add the watchlist bridge sentence.
   Separate stories with exactly: ---TRANSITION---

4. MARKETS (~4 minutes)
   Carmen covers company news as ONE single flowing narrative — she moves
   naturally between companies in the priority order given, connecting themes
   where they exist ("Meanwhile in the AI space…", "On the semiconductor front…").
   IMPORTANT RULES FOR THIS SEGMENT:
   - Write it ONCE, straight through, start to finish.
   - Cover each company exactly ONE time — never summarise first then repeat.
   - Select the 8–10 most newsworthy items; you do not need to mention every company.
   - No prices or numbers — news and developments only.
   - Do NOT place any ---TRANSITION--- markers inside this segment.
   - End the segment with exactly one: ---TRANSITION---

5. CLOSING (~30 seconds)
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
            "maxOutputTokens": 16384,
        },
    }
    retries = 8
    for attempt in range(1, retries + 1):
        try:
            resp = requests.post(
                GEMINI_URL,
                params={"key": GEMINI_API_KEY},
                json=payload,
                timeout=120,
            )
            if resp.status_code in (429, 503, 529) and attempt < retries:
                wait = min(30 * (2 ** (attempt - 1)), 300)  # 30s, 60s, 120s, 240s, 300s cap
                print(f"  Gemini {resp.status_code} — retrying in {wait}s (attempt {attempt}/{retries})…")
                time.sleep(wait)
                continue
            resp.raise_for_status()
            data      = resp.json()
            candidate = data["candidates"][0]
            finish    = candidate.get("finishReason", "UNKNOWN")
            text      = candidate["content"]["parts"][0]["text"]
            print(f"  Gemini finishReason: {finish} ({len(text)} chars)")
            if finish not in ("STOP", "MAX_TOKENS"):
                print(f"  WARNING: unexpected finishReason '{finish}' — script may be incomplete.")
            return text
        except requests.exceptions.ReadTimeout:
            if attempt < retries:
                wait = min(30 * (2 ** (attempt - 1)), 300)
                print(f"  Gemini timeout — retrying in {wait}s (attempt {attempt}/{retries})…")
                time.sleep(wait)
            else:
                raise
    raise RuntimeError("Gemini call failed after all retries")


def openai_call(prompt: str) -> str:
    """Fallback to OpenAI GPT when Gemini is unavailable."""
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY not set — cannot use OpenAI fallback.")
    payload = {
        "model": OPENAI_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": prompt},
        ],
        "temperature": 0.7,
        "max_tokens": 4096,
    }
    retries = 4
    for attempt in range(1, retries + 1):
        try:
            resp = requests.post(
                OPENAI_URL,
                headers={"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"},
                json=payload,
                timeout=120,
            )
            if resp.status_code in (429, 503) and attempt < retries:
                wait = 30 * attempt
                print(f"  OpenAI {resp.status_code} — retrying in {wait}s (attempt {attempt}/{retries})…")
                time.sleep(wait)
                continue
            resp.raise_for_status()
            data = resp.json()
            text = data["choices"][0]["message"]["content"]
            print(f"  OpenAI fallback succeeded ({len(text)} chars).")
            return text
        except requests.exceptions.ReadTimeout:
            if attempt < retries:
                time.sleep(30 * attempt)
            else:
                raise
    raise RuntimeError("OpenAI fallback also failed after all retries")


def llm_call(prompt: str, dry_run: bool = False) -> str:
    """Call Gemini; fall back to OpenAI if Gemini is persistently unavailable."""
    try:
        return gemini_call(prompt, dry_run)
    except Exception as gemini_err:
        if dry_run:
            raise
        print(f"  Gemini exhausted ({gemini_err}). Trying OpenAI fallback…", file=sys.stderr)
        return openai_call(prompt)


def enforce_tier_diversity(all_stories: list[dict], prioritised: list[dict]) -> list[dict]:
    """
    Guarantee at least one Tier 2 and one Tier 3 company in the final feed.

    If a tier is absent from the prioritised slice, the highest-scoring story
    from that tier is appended (drawn from the full scored list).
    This ensures lower-tier companies with real news always get a voice.
    """
    result = list(prioritised)
    included_tiers = {s.get("tier") for s in result}

    for required_tier in (2, 3):
        if required_tier not in included_tiers:
            candidates = sorted(
                [s for s in all_stories if s.get("tier") == required_tier],
                key=lambda x: -x.get("score", 0),
            )
            if candidates:
                best = candidates[0]
                result.append(best)
                print(
                    f"  Forced Tier {required_tier} inclusion: "
                    f"{best.get('name', best.get('ticker', '?'))} "
                    f"(score={best.get('score', '?')})"
                )

    return result


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

    # Load strategic stories — prefer new file, fall back to legacy geo_stories.json
    if STRATEGIC_FILE.exists():
        strategic_stories = load_json(STRATEGIC_FILE, "strategic_stories")
    elif GEO_FILE.exists():
        print("  NOTE: strategic_stories.json not found — falling back to geo_stories.json")
        strategic_stories = load_json(GEO_FILE, "geo_stories")
    else:
        print("ERROR: No strategic stories file found.", file=sys.stderr)
        sys.exit(1)

    # Load tech stories — empty list if not yet generated (graceful degradation)
    if TECH_FILE.exists():
        tech_stories = load_json(TECH_FILE, "tech_stories")
    else:
        print("  NOTE: tech_stories.json not found — AI & Tech segment will be empty.")
        tech_stories = []

    market_stories = load_json(MARKET_FILE, "market_stories")

    # Apply watchlist prioritisation, cap to top 15, then guarantee
    # at least one Tier 2 and one Tier 3 company is included.
    market_stories_sorted = prioritise_stories(market_stories)
    market_stories = enforce_tier_diversity(market_stories_sorted, market_stories_sorted[:15])
    print(
        f"Using {len(strategic_stories)} strategic + "
        f"{len(tech_stories)} tech + "
        f"{len(market_stories)} market stories."
    )

    today = date.today().strftime("%A, %d %B %Y")

    prompt = (
        f"Today's date: {today}\n\n"
        "GLOBAL STRATEGIC AFFAIRS STORIES (in selected order, present in this sequence):\n"
        + json.dumps(strategic_stories, indent=2, ensure_ascii=False)
        + "\n\nAI & TECH STORIES (in selected order, present in this sequence):\n"
        + json.dumps(tech_stories, indent=2, ensure_ascii=False)
        + "\n\nCOMPANY NEWS (in priority order, present as single narrative):\n"
        + json.dumps(market_stories, indent=2, ensure_ascii=False)
    )

    print("Generating Carmen's script via Gemini…")
    script = llm_call(prompt, args.dry_run)

    SCRIPT_FILE.write_text(script, encoding="utf-8")
    print(f"Script saved → {SCRIPT_FILE} ({len(script)} chars)")

    # Save episode metadata sidecar for the PWA Episode Details module
    def _story_meta(s: dict) -> dict:
        return {
            "headline":        s.get("headline", ""),
            "summary_snippet": s.get("summary_snippet", ""),
            "source_url":      s.get("source_url", ""),
            "topic":           s.get("topic", []),
            "score":           s.get("score", 5),
            "watchlist_flag":  s.get("watchlist_flag", False),
            "watchlist_note":  s.get("watchlist_note", ""),
        }

    def _market_meta(s: dict) -> dict:
        return {
            "headline":        s.get("headline", ""),
            "summary_snippet": s.get("summary_snippet", ""),
            "source_url":      s.get("source_url", ""),
            "ticker":          s.get("ticker", ""),
            "name":            s.get("name", ""),
            "tier":            s.get("tier", 3),
            "score":           s.get("score", 5),
        }

    metadata = {
        "date":               date.today().isoformat(),
        "strategic_stories":  [_story_meta(s) for s in strategic_stories],
        "tech_stories":       [_story_meta(s) for s in tech_stories],
        "market_stories":     [_market_meta(s) for s in market_stories],
        # backward-compat alias
        "geo_stories":        [_story_meta(s) for s in strategic_stories],
    }
    METADATA_FILE.write_text(json.dumps(metadata, indent=2, ensure_ascii=False))
    print(f"Episode metadata saved → {METADATA_FILE}")

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
