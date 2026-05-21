"""
Convert each script segment to an MP3 using edge-tts.
Reads tmp/segments.json → writes tmp/segments/segment_NN.mp3

Usage:
    python scripts/synthesise_audio.py [--dry-run]
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

import edge_tts

# Voice configuration — change CARMEN_VOICE to switch accents:
#   en-US-AriaNeural       (American English, warm)
#   en-GB-SoniaNeural      (British English)
#   en-AU-NatashaNeural    (Australian English)
CARMEN_VOICE = "en-US-AriaNeural"
CARMEN_RATE  = "+0%"    # Try "+5%" for slightly faster delivery
CARMEN_PITCH = "+0Hz"

TMP_DIR = Path("tmp")
SEGMENTS_JSON = TMP_DIR / "segments.json"
OUT_DIR = TMP_DIR / "segments"


async def synthesise_segment(text: str, out_path: Path) -> None:
    communicate = edge_tts.Communicate(text, CARMEN_VOICE, rate=CARMEN_RATE, pitch=CARMEN_PITCH)
    await communicate.save(str(out_path))


async def main_async(dry_run: bool) -> None:
    if not SEGMENTS_JSON.exists():
        print(f"ERROR: {SEGMENTS_JSON} not found. Run generate_script.py first.", file=sys.stderr)
        sys.exit(1)

    with SEGMENTS_JSON.open() as f:
        segments = json.load(f)

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Synthesising {len(segments)} segments with voice: {CARMEN_VOICE}")
    for i, text in enumerate(segments):
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
