"""
Convert each script segment to an MP3 using edge-tts.
Reads tmp/segments.json → writes tmp/segments/segment_NN.mp3

Usage:
    python scripts/synthesise_audio.py [--dry-run]
"""

import argparse
import asyncio
import html
import json
import re
import sys
from pathlib import Path

import edge_tts

# ── Voice and SSML tuning constants ──────────────────────────────────────────
# Change CARMEN_VOICE to switch accent:
#   en-US-AriaNeural       (American English, warm)
#   en-GB-SoniaNeural      (British English)
#   en-AU-NatashaNeural    (Australian English)
CARMEN_VOICE         = "en-US-AriaNeural"
CARMEN_RATE          = "-6%"     # Slightly slower than default; increase toward 0% if too slow
CARMEN_PITCH         = "+0Hz"    # Leave at 0 unless voice sounds unnatural
TRANSITION_BREAK_MS  = 800       # SSML pause replacing any inline ---TRANSITION--- markers
PARAGRAPH_BREAK_MS   = 400       # SSML pause between paragraph breaks (\n\n)

TMP_DIR = Path("tmp")
SEGMENTS_JSON  = TMP_DIR / "segments.json"
SSML_DEBUG_FILE = TMP_DIR / "script_ssml.txt"
OUT_DIR = TMP_DIR / "segments"


# Strips markdown artifacts Gemini sometimes slips in (e.g. "### Markets")
# despite being told to write spoken-only text — edge-tts otherwise reads
# "#", "*", "_" and backtick characters aloud.
MARKDOWN_ARTIFACTS = re.compile(r"[#*_`]")


def clean_for_speech(text: str) -> str:
    return MARKDOWN_ARTIFACTS.sub("", text)


_BREAK_RE = re.compile(r'%%BREAK(\d+)ms%%')


def prepare_ssml_content(text: str) -> str:
    """Convert structural markers to %%BREAKXXXms%% placeholders.

    Placeholders use only safe characters (%,digits,m,s) that html.escape()
    leaves untouched. They are converted to real SSML <break> tags in
    escape_for_ssml() after XML escaping, guaranteeing html.escape() never
    corrupts them.

    edge-tts 7.x wraps the text in <speak><voice><prosody> internally — only
    inner SSML elements are needed here; no outer <speak> wrapper.
    """
    # Safety net: convert any surviving ---TRANSITION--- markers
    text = text.replace("---TRANSITION---", f'%%BREAK{TRANSITION_BREAK_MS}ms%%')
    # Paragraph breaks → medium pause placeholder
    text = text.replace("\n\n", f'%%BREAK{PARAGRAPH_BREAK_MS}ms%%')
    # Single newlines → space
    text = text.replace("\n", " ")
    return text


def escape_for_ssml(text: str) -> str:
    """Escape XML chars, then convert break placeholders to SSML break tags.

    Order is critical: html.escape() runs first on plain text, then the
    placeholders (which survived escaping unchanged) become real SSML elements.
    This guarantees the break tags are never touched by html.escape().
    """
    text = html.escape(text, quote=False)
    text = _BREAK_RE.sub(r'<break time="\1ms"/>', text)
    return text


async def synthesise_segment(text: str, out_path: Path) -> str:
    """Synthesise one segment to MP3. Returns the processed SSML content for debug logging."""
    text = prepare_ssml_content(text)
    text = escape_for_ssml(text)
    communicate = edge_tts.Communicate(text, CARMEN_VOICE, rate=CARMEN_RATE, pitch=CARMEN_PITCH)
    await communicate.save(str(out_path))
    return text


async def main_async(dry_run: bool) -> None:
    if not SEGMENTS_JSON.exists():
        print(f"ERROR: {SEGMENTS_JSON} not found. Run generate_script.py first.", file=sys.stderr)
        sys.exit(1)

    with SEGMENTS_JSON.open() as f:
        segments = json.load(f)

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # Remove stale segment files from previous runs — otherwise leftover
    # segments from a day with more stories than today get picked up by
    # stitch_audio.py's glob and tacked onto the end of the episode.
    if not dry_run:
        for stale in OUT_DIR.glob("segment_*.mp3"):
            stale.unlink()

    print(f"Synthesising {len(segments)} segments with voice: {CARMEN_VOICE}")
    ssml_parts: list[str] = []
    for i, text in enumerate(segments):
        text = clean_for_speech(text)
        out_path = OUT_DIR / f"segment_{i:02d}.mp3"
        if dry_run:
            print(f"  [DRY-RUN] Would synthesise segment {i:02d} ({len(text)} chars) → {out_path}")
            continue
        print(f"  Synthesising segment {i:02d} ({len(text)} chars)…")
        ssml_text = await synthesise_segment(text, out_path)
        ssml_parts.append(f"--- Segment {i:02d} ---\n{ssml_text}")
        print(f"    → {out_path}")

    if not dry_run:
        SSML_DEBUG_FILE.write_text("\n\n".join(ssml_parts), encoding="utf-8")
        print(f"Done. Audio segments in {OUT_DIR}/")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    asyncio.run(main_async(args.dry_run))


if __name__ == "__main__":
    main()
