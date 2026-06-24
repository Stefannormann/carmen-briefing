"""
Convert each script segment to an MP3 using edge-tts.
Reads tmp/segments.json → writes tmp/segments/segment_NN.mp3

Usage:
    python scripts/synthesise_audio.py [--dry-run]
"""

import argparse
import asyncio
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
SEGMENTS_JSON = TMP_DIR / "segments.json"
OUT_DIR = TMP_DIR / "segments"


# Strips markdown artifacts Gemini sometimes slips in (e.g. "### Markets")
# despite being told to write spoken-only text — edge-tts otherwise reads
# "#", "*", "_" and backtick characters aloud.
MARKDOWN_ARTIFACTS = re.compile(r"[#*_`]")


def clean_for_speech(text: str) -> str:
    return MARKDOWN_ARTIFACTS.sub("", text)


def wrap_in_ssml(
    text: str,
    voice: str = CARMEN_VOICE,
    rate: str  = CARMEN_RATE,
    pitch: str = CARMEN_PITCH,
) -> str:
    """Wrap cleaned segment text in SSML for edge-tts synthesis."""
    # Safety net: convert any surviving ---TRANSITION--- markers to SSML breaks
    text = text.replace("---TRANSITION---", f'<break time="{TRANSITION_BREAK_MS}ms"/>')
    # Convert paragraph breaks to medium pauses
    text = text.replace("\n\n", f'<break time="{PARAGRAPH_BREAK_MS}ms"/>')
    # Single newlines become a short pause
    text = text.replace("\n", " ")

    return (
        f'<speak version="1.0" '
        f'xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="en-US">'
        f'<voice name="{voice}">'
        f'<prosody rate="{rate}" pitch="{pitch}">'
        f'{text}'
        f'</prosody>'
        f'</voice>'
        f'</speak>'
    )


async def synthesise_segment(text: str, out_path: Path) -> None:
    ssml = wrap_in_ssml(text)
    communicate = edge_tts.Communicate(ssml, CARMEN_VOICE, ssml=True)
    await communicate.save(str(out_path))


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
    for i, text in enumerate(segments):
        text = clean_for_speech(text)
        out_path = OUT_DIR / f"segment_{i:02d}.mp3"
        if dry_run:
            print(f"  [DRY-RUN] Would synthesise segment {i:02d} ({len(text)} chars) → {out_path}")
            continue
        print(f"  Synthesising segment {i:02d} ({len(text)} chars)…")
        await synthesise_segment(text, out_path)
        print(f"    → {out_path}")

    if not dry_run:
        print(f"Done. Audio segments in {OUT_DIR}/")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    asyncio.run(main_async(args.dry_run))


if __name__ == "__main__":
    main()
