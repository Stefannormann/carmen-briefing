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
import tempfile
from pathlib import Path

import edge_tts
from pydub import AudioSegment

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

    edge-tts 7.x's Communicate class XML-escapes the *entire* input text
    before embedding it in its own <speak><voice><prosody> template (see
    Communicate.__init__ in edge_tts/communicate.py). That means any literal
    <break> tag we hand it gets escaped to "&lt;break .../&gt;" and read back
    aloud as words — inline SSML injection is not supported by this version.
    So these placeholders are never turned into <break> tags; split_into_chunks()
    below uses them to splice in real silence with pydub instead.
    """
    # Safety net: convert any surviving ---TRANSITION--- markers
    text = text.replace("---TRANSITION---", f'%%BREAK{TRANSITION_BREAK_MS}ms%%')
    # Paragraph breaks → medium pause placeholder
    text = text.replace("\n\n", f'%%BREAK{PARAGRAPH_BREAK_MS}ms%%')
    # Single newlines → space
    text = text.replace("\n", " ")
    return text


def split_into_chunks(text: str) -> list[tuple[str, int]]:
    """Split placeholder-marked text into (spoken_text, trailing_pause_ms) pairs."""
    parts = _BREAK_RE.split(text)
    chunks = [(parts[i], int(parts[i + 1])) for i in range(0, len(parts) - 1, 2)]
    chunks.append((parts[-1], 0))
    return [(t.strip(), ms) for t, ms in chunks if t.strip() or ms]


async def synthesise_segment(text: str, out_path: Path) -> str:
    """Synthesise one segment to MP3, splicing real silence at break points.

    Returns a debug string describing the chunk/pause structure for logging.
    """
    text = prepare_ssml_content(text)
    chunks = split_into_chunks(text)

    audio = AudioSegment.empty()
    debug_parts = []
    with tempfile.TemporaryDirectory() as tmpdir:
        for idx, (chunk_text, pause_ms) in enumerate(chunks):
            if chunk_text:
                part_path = Path(tmpdir) / f"part_{idx:02d}.mp3"
                communicate = edge_tts.Communicate(
                    chunk_text, CARMEN_VOICE, rate=CARMEN_RATE, pitch=CARMEN_PITCH
                )
                await communicate.save(str(part_path))
                audio += AudioSegment.from_mp3(str(part_path))
                debug_parts.append(chunk_text)
            if pause_ms:
                audio += AudioSegment.silent(duration=pause_ms)
                debug_parts.append(f'<break time="{pause_ms}ms"/>')

    audio.export(str(out_path), format="mp3")
    return " ".join(debug_parts)


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
