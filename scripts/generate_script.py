"""
Generate Carmen's spoken script via Gemini, using scored geo and market stories.
Saves full script to tmp/script.txt and segment list to tmp/segments.json.

Usage:
    python scripts/generate_script.py [--dry-run]
"""

import argparse
import json
import os
import re
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
SCRIPT_FILE           = TMP_DIR / "script.txt"
SCRIPT_RAW_FILE       = TMP_DIR / "script_raw.txt"
SCRIPT_SANITISED_FILE = TMP_DIR / "script_sanitised.txt"
SEGMENTS_FILE     = TMP_DIR / "segments.json"
STRATEGIC_FILE    = TMP_DIR / "strategic_stories.json"
TECH_FILE         = TMP_DIR / "tech_stories.json"
GEO_FILE          = TMP_DIR / "geo_stories.json"   # backward-compat fallback
MARKET_FILE       = TMP_DIR / "market_stories.json"
METADATA_FILE     = TMP_DIR / "episode_metadata.json"

TRANSITION_MARKER = "---TRANSITION---"


def format_for_tts(text: str) -> str:
    """
    Post-process the LLM script to improve naturalness for edge-tts synthesis.
    Applied after LLM generation, before segmenting on TRANSITION_MARKER.
    """
    # 1. Replace comma-heavy pauses with em-dashes for longer natural breaks.
    #    Targets commas that follow words of 4+ characters.
    text = re.sub(r'(\w{4,}),\s', r'\1 — ', text)

    # 2. Add ellipsis before reveal-style words for dramatic pacing.
    #    e.g. "The answer is China" → "The answer is... China"
    text = re.sub(r'\b(is|are|was|were|means|signals|suggests)\s+([A-Z])', r'\1... \2', text)

    # 3. Break sentences longer than 20 words at natural conjunction points.
    sentences = text.split('. ')
    formatted = []
    for sentence in sentences:
        words = sentence.split()
        if len(words) > 20:
            sentence = re.sub(
                r'\s+(and|but|which|because|however)\s+', r'. \1 ', sentence, count=1
            )
        formatted.append(sentence)
    text = '. '.join(formatted)

    return text


def sanitise_script(text: str) -> str:
    """Strip symbols and formatting that would be read aloud literally by the TTS engine.

    Runs on the raw LLM output before format_for_tts() and before segmenting.
    Acts as a safety net regardless of what the LLM returns.
    """
    # Protect TRANSITION markers before any --- substitution.
    # Also promote bare --- section dividers (Gemini's common fallback when
    # it misreads the no-em-dash-as-dashes rule) to full TRANSITION markers.
    text = text.replace("---TRANSITION---", "%%TRANSITION%%")
    text = re.sub(r'(?m)^---\s*$', '%%TRANSITION%%', text)

    # Remove markdown bold and italic
    text = re.sub(r'\*{1,3}(.*?)\*{1,3}', r'\1', text)

    # Remove markdown headers
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)

    # Remove URLs entirely
    text = re.sub(r'https?://\S+', '', text)
    text = re.sub(r'www\.\S+', '', text)

    # Remove domain-style references (e.g. reuters.com, ft.com)
    text = re.sub(r'\b\w+\.(com|org|net|io|gov|dk|eu|co)\b', '', text)

    # Convert & to "and" so it survives XML escaping downstream
    text = text.replace('&', ' and ')

    # Replace -- or --- with em-dash
    text = re.sub(r'---', '—', text)
    text = re.sub(r'--', '—', text)

    # Convert any pause markers Gemini might emit into break placeholders.
    # %%BREAKXXXms%% uses only safe characters that survive html.escape() unchanged.
    # Real SSML <break> tags are inserted AFTER XML escaping in synthesise_audio.py.
    # This block must run before the <> stripping below.

    # <break time="400ms"/> or malformed <break time=400ms/>
    text = re.sub(
        r'<break\s+time=["\']?(\d+)\s*ms["\']?\s*/?>',
        lambda m: f'%%BREAK{m.group(1)}ms%%',
        text, flags=re.IGNORECASE,
    )
    # [pause=400ms] or [pause=400]
    text = re.sub(
        r'\[pause[=\s]*(\d+)\s*m?s?\]',
        lambda m: f'%%BREAK{m.group(1)}ms%%',
        text, flags=re.IGNORECASE,
    )
    # (pause 400ms) or (pause 400 milliseconds)
    text = re.sub(
        r'\(\s*pause\s+(\d+)\s*(?:ms|milliseconds?)?\s*\)',
        lambda m: f'%%BREAK{m.group(1)}ms%%',
        text, flags=re.IGNORECASE,
    )
    # pause=400ms or pause=400 as bare text
    text = re.sub(
        r'\bpause\s*=\s*(\d+)\s*(?:ms|milliseconds?)?\b',
        lambda m: f'%%BREAK{m.group(1)}ms%%',
        text, flags=re.IGNORECASE,
    )
    # Remove standalone [pause] / (pause) with no duration
    text = re.sub(r'\[\s*pause\s*\]', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\(\s*pause\s*\)', '', text, flags=re.IGNORECASE)
    # Clamp all break durations to a reasonable range (100–2000ms)
    def _clamp_break(m: re.Match) -> str:
        ms = max(100, min(int(m.group(1)), 2000))
        return f'%%BREAK{ms}ms%%'
    text = re.sub(r'%%BREAK(\d+)ms%%', _clamp_break, text)

    # Replace forward slash used as "or" / "and" with natural alternative
    text = re.sub(r'(\w+)/(\w+)', r'\1 or \2', text)

    # Remove remaining special characters with no spoken equivalent
    text = re.sub(r'[\\=|<>{}\[\]@~^`#]', '', text)

    # Clean up duplicate spaces and extra blank lines created by removals above
    text = re.sub(r'[ \t]{2,}', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)

    # Restore TRANSITION markers
    text = text.replace("%%TRANSITION%%", "---TRANSITION---")

    return text.strip()


SYSTEM_PROMPT = """\
You are a professional radio script writer for a daily morning news briefing podcast.
The host is Carmen — a warm, engaging, professional female journalist who speaks
directly to the listener as if on a morning radio show.
Her tone is confident but approachable. She does not read bullet points —
she speaks in natural, flowing, broadcaster sentences.

Write the complete spoken script for today's episode.
Do NOT include stage directions, sound cues, or production notes.
Write only Carmen's spoken words.

WRITING STYLE — RADIO FORMATTING:
- Prefer short, punchy sentences. Target 12–15 words maximum per sentence.
- Use em-dashes (—) rather than commas where a longer pause would feel natural on radio.
- Never chain more than two clauses with commas in a single sentence.
- Vary sentence length deliberately — short sentences land harder after longer ones.

CRITICAL FORMATTING RULES — these apply to every word of the script:
- Write in plain spoken English only. No markdown, no formatting symbols.
- Do not use: **, *, #, /, \\, =, |, <, >, [], {}, @, ~, ^, `
- Do not include URLs, domain names, or web addresses anywhere in the script.
- Do not write source attributions with slashes or punctuation — if attributing a source,
  write it as natural speech only, e.g. "according to Reuters" not "Reuters.com".
- Use only standard punctuation: period, comma, em-dash, ellipsis, question mark, exclamation mark.
- Em-dashes must be written as — (the actual Unicode character), not as -- or ---
- Do NOT write bare --- as a section divider or horizontal rule. Use ---TRANSITION--- instead.
- The only non-spoken marker allowed in the script is the exact string ---TRANSITION--- on its own line.
  Note: ---TRANSITION--- is explicitly exempt from the no-dashes rule above — it is required.

CRITICAL — PAUSE AND TIMING RULES:
- Do NOT write any pause instructions, timing markers, or break commands in the script.
- Do NOT write anything like: [pause], pause=Xms, <break>, (pause), [break], or any variation.
- Do NOT write technical instructions of any kind inside the script text.
- Pauses are handled automatically by the audio pipeline. Write spoken words only.
- To create a natural pause in speech, use punctuation: a period, an em-dash (—), or an ellipsis (...).
  These are interpreted as pauses automatically. Never write the word "pause" as an instruction.

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

    # ── Day-of-week episode rules ──────────────────────────────────────────────
    today_weekday = date.today().weekday()   # 0=Mon, 1=Tue, 2=Wed, 3=Thu, 4=Fri
    is_short_episode = today_weekday in (1, 2, 3, 4)   # Tue–Fri: 6-minute format
    is_wednesday = today_weekday == 2

    if is_short_episode:
        strategic_stories = strategic_stories[:2]
        tech_stories      = tech_stories[:2]

    # Wednesday markets segment: reduced tier debuff so Tier 2/3 stories compete
    tier_debuff = 0.4 if is_wednesday else 1.0
    market_stories_sorted = prioritise_stories(market_stories, tier_debuff_multiplier=tier_debuff)

    # Cap market candidates: tighter pool for short episodes
    market_cap = 7 if is_short_episode else 15
    market_stories = enforce_tier_diversity(market_stories_sorted, market_stories_sorted[:market_cap])

    print(
        f"Using {len(strategic_stories)} strategic + "
        f"{len(tech_stories)} tech + "
        f"{len(market_stories)} market stories."
        + (f" [short episode, tier_debuff={tier_debuff}]" if is_short_episode else "")
    )

    # ── Markets time budget for short episodes ─────────────────────────────────
    markets_budget_secs: int | None = None
    if is_short_episode:
        macro_secs = len(strategic_stories) * 90
        tech_secs  = len(tech_stories) * 90
        markets_budget_secs = max(360 - 60 - macro_secs - tech_secs, 60)

    today = date.today().strftime("%A, %d %B %Y")

    prompt = f"Today's date: {today}\n\n"

    if is_short_episode:
        macro_n    = len(strategic_stories)
        tech_n     = len(tech_stories)
        macro_secs = macro_n * 90
        tech_secs  = tech_n * 90
        prompt += (
            "EPISODE SCHEDULING CONTEXT — FOLLOW EXACTLY:\n"
            "Episode type: SHORTENED (Tuesday–Friday format)\n"
            f"Target total duration: 6 minutes (360 seconds)\n"
            f"Budget breakdown:\n"
            f"  Intro + closing:          ~60 seconds\n"
            f"  Global Strategic Affairs: {macro_n} stor{'y' if macro_n == 1 else 'ies'}"
            f" × ~90 seconds = ~{macro_secs} seconds\n"
            f"  AI & Tech:                {tech_n} stor{'y' if tech_n == 1 else 'ies'}"
            f" × ~90 seconds = ~{tech_secs} seconds\n"
            f"  Markets segment:          ~{markets_budget_secs} seconds remaining\n"
            "\n"
            "STRUCTURE OVERRIDES FOR THIS EPISODE:\n"
            "1. INTRO — 20 seconds max; one short sentence per segment preview\n"
            f"2. GLOBAL STRATEGIC AFFAIRS — cover exactly {macro_n}"
            f" stor{'y' if macro_n == 1 else 'ies'}, ~90 seconds each\n"
            f"3. AI & TECH — cover exactly {tech_n}"
            f" stor{'y' if tech_n == 1 else 'ies'}, ~90 seconds each\n"
            f"4. MARKETS — single flowing narrative;"
            f" fit within {markets_budget_secs} seconds;"
            f" cover {max(1, markets_budget_secs // 90)} compan{'y' if markets_budget_secs // 90 <= 1 else 'ies'} maximum\n"
            "5. CLOSING — 20 seconds max; brief sign-off only\n"
            "\n"
            "CRITICAL: Do NOT pad, repeat, or extend beyond the time budget.\n"
            "Do NOT cover more stories than specified above.\n"
            "Write tighter, more concise sentences than the standard format.\n"
            "Every sentence must earn its place. Stop when the budget is spent.\n\n"
        )

    prompt += (
        "GLOBAL STRATEGIC AFFAIRS STORIES (in selected order, present in this sequence):\n"
        + json.dumps(strategic_stories, indent=2, ensure_ascii=False)
        + "\n\nAI & TECH STORIES (in selected order, present in this sequence):\n"
        + json.dumps(tech_stories, indent=2, ensure_ascii=False)
        + "\n\nCOMPANY NEWS (in priority order, present as single narrative):\n"
        + json.dumps(market_stories, indent=2, ensure_ascii=False)
    )

    print("Generating Carmen's script via Gemini…")
    raw_script = llm_call(prompt, args.dry_run)
    SCRIPT_RAW_FILE.write_text(raw_script, encoding="utf-8")

    sanitised_script = sanitise_script(raw_script)
    SCRIPT_SANITISED_FILE.write_text(sanitised_script, encoding="utf-8")

    script = format_for_tts(sanitised_script)
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
