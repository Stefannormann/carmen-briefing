"""
Stitch jingle + speech segments + transitions into the final episode MP3.
Output: episodes/YYYY-MM-DD.mp3

Usage:
    python scripts/stitch_audio.py [--dry-run]
"""

import argparse
import json
import sys
from datetime import date
from pathlib import Path

TMP_DIR = Path("tmp")
SEGMENTS_DIR = TMP_DIR / "segments"
AUDIO_DIR = Path("audio")
EPISODES_DIR = Path("episodes")

JINGLE = AUDIO_DIR / "jingle.mp3"
TRANSITION = AUDIO_DIR / "transition.mp3"

# Target loudness for normalisation (LUFS)
TARGET_LUFS = -18.0


def load_audio(path: Path):
    """Load an MP3 file as a pydub AudioSegment."""
    from pydub import AudioSegment
    return AudioSegment.from_mp3(str(path))


def normalise(segment, target_dbfs: float = -18.0):
    """Normalise a segment to a target dBFS level. Skips silent segments."""
    if segment.dBFS == float("-inf"):
        return segment  # silent segment — return as-is to avoid inf gain
    diff = target_dbfs - segment.dBFS
    return segment.apply_gain(diff)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.dry_run:
        print("[DRY-RUN] stitch_audio.py: would assemble episode but skipping audio I/O.")
        print("          Requires synthesise_audio.py to have run first.")
        return

    from pydub import AudioSegment

    # Gather segment files in order
    segment_files = sorted(SEGMENTS_DIR.glob("segment_*.mp3"))
    if not segment_files:
        print(f"ERROR: No segment files found in {SEGMENTS_DIR}. Run synthesise_audio.py first.",
              file=sys.stderr)
        sys.exit(1)

    print(f"Found {len(segment_files)} speech segments.")

    # Check for audio assets
    missing = [p for p in [JINGLE, TRANSITION] if not p.exists()]
    if missing:
        print(f"ERROR: Missing audio assets: {missing}", file=sys.stderr)
        print("       Run download_audio_assets.py first.", file=sys.stderr)
        sys.exit(1)

    # Load and normalise base audio assets
    jingle = normalise(load_audio(JINGLE))
    transition = normalise(load_audio(TRANSITION))

    print("Assembling episode…")
    episode = AudioSegment.empty()

    # Jingle first
    episode += jingle

    # Interleave speech segments with transitions
    for i, seg_file in enumerate(segment_files):
        segment = normalise(load_audio(seg_file))
        if i > 0:
            episode += transition
        episode += segment
        print(f"  + {seg_file.name} ({len(segment)/1000:.1f}s)")

    EPISODES_DIR.mkdir(exist_ok=True)
    today = date.today().isoformat()
    out_path = EPISODES_DIR / f"{today}.mp3"

    print(f"Exporting → {out_path}")
    episode.export(str(out_path), format="mp3", bitrate="128k",
                   tags={"title": f"Carmen's Briefing — {today}",
                         "artist": "Carmen",
                         "album": "Carmen Daily Briefing"})

    duration_seconds = len(episode) // 1000
    print(f"Episode duration: {duration_seconds}s ({duration_seconds//60}m {duration_seconds%60}s)")
    print(f"Saved: {out_path}")


if __name__ == "__main__":
    main()
