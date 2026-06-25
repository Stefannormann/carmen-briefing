"""
Stitch jingle + speech segments + transitions into the final episode MP3.
Output: episodes/YYYY-MM-DD.mp3

Usage:
    python scripts/stitch_audio.py [--dry-run]
"""

import argparse
import os
import subprocess
import sys
from datetime import date
from pathlib import Path

TMP_DIR = Path("tmp")
SEGMENTS_DIR = TMP_DIR / "segments"
AUDIO_DIR = Path("audio")
EPISODES_DIR = Path("episodes")

JINGLE       = AUDIO_DIR / "jingle.mp3"
TRANSITION   = AUDIO_DIR / "transition.mp3"

# Target loudness for normalisation
TARGET_LUFS = -18.0

# ── Audio dressing tuning constants ──────────────────────────────────────────
# EQ: bass boost via ffmpeg equalizer filter
EQ_FREQUENCY  = 100     # Hz — centre frequency for warmth boost
EQ_WIDTH      = 2       # octaves — bandwidth of the boost
EQ_GAIN_DB    = 3       # dB — boost amount; reduce to 1 if too muddy

VALIDATE_MIN_DURATION_MS = 5_000  # guard: abort if audio shorter than 5 seconds


def load_audio(path: Path):
    from pydub import AudioSegment
    return AudioSegment.from_mp3(str(path))


def normalise(segment, target_dbfs: float = -18.0):
    """Normalise a segment to a target dBFS level. Skips silent segments."""
    if segment.dBFS == float("-inf"):
        return segment  # silent segment — return as-is to avoid inf gain
    diff = target_dbfs - segment.dBFS
    return segment.apply_gain(diff)


def apply_warmth_filter(audio):
    """Light dynamic range compression to even out Carmen's voice level."""
    from pydub.effects import compress_dynamic_range
    return compress_dynamic_range(audio, threshold=-20.0, ratio=3.0, attack=5.0, release=50.0)


def validate_audio(audio, step_name: str, min_duration_ms: int = VALIDATE_MIN_DURATION_MS) -> None:
    """Abort if audio is too short or silent after a pipeline step."""
    duration_ms = len(audio)
    if duration_ms < min_duration_ms:
        print(
            f"ERROR [validate_audio]: after '{step_name}', audio is only {duration_ms}ms "
            f"(minimum {min_duration_ms}ms). Aborting.",
            file=sys.stderr,
        )
        sys.exit(1)
    if audio.dBFS == float("-inf"):
        print(
            f"ERROR [validate_audio]: after '{step_name}', audio is completely silent. Aborting.",
            file=sys.stderr,
        )
        sys.exit(1)
    print(f"  [OK] {step_name}: {duration_ms // 1000}s, {audio.dBFS:.1f} dBFS")


def apply_eq_via_ffmpeg(input_path: str, output_path: str) -> None:
    """Apply bass-boost EQ to the exported episode file via ffmpeg."""
    subprocess.run(
        [
            "ffmpeg", "-y", "-i", input_path,
            "-af", f"equalizer=f={EQ_FREQUENCY}:width_type=o:width={EQ_WIDTH}:g={EQ_GAIN_DB}",
            output_path,
        ],
        check=True,
        capture_output=True,
    )


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

    validate_audio(episode, "stitch")

    # ── Audio dressing ────────────────────────────────────────────────────────
    # Step 1: Light compression for consistent dynamics
    print("Applying warmth filter (compression)…")
    episode = apply_warmth_filter(episode)
    validate_audio(episode, "warmth filter")

    EPISODES_DIR.mkdir(exist_ok=True)
    today = date.today().isoformat()
    out_path = EPISODES_DIR / f"{today}.mp3"

    # Step 2: Export assembled episode
    print(f"Exporting → {out_path}")
    episode.export(str(out_path), format="mp3", bitrate="128k",
                   tags={"title": f"Carmen's Briefing — {today}",
                         "artist": "Carmen",
                         "album": "Carmen Daily Briefing"})

    # Step 3: Apply EQ via ffmpeg (bass boost for warmth)
    eq_tmp = out_path.with_name(out_path.stem + "_eq_tmp.mp3")
    try:
        apply_eq_via_ffmpeg(str(out_path), str(eq_tmp))
        os.replace(str(eq_tmp), str(out_path))
        print(f"EQ applied (+{EQ_GAIN_DB}dB @ {EQ_FREQUENCY}Hz).")
        eq_check = load_audio(out_path)
        validate_audio(eq_check, "EQ")
    except SystemExit:
        raise
    except Exception as e:
        print(f"  WARN: EQ step failed ({e}) — keeping pre-EQ file.", file=sys.stderr)
        if eq_tmp.exists():
            eq_tmp.unlink()

    duration_seconds = len(episode) // 1000
    print(f"Episode duration: {duration_seconds}s ({duration_seconds//60}m {duration_seconds%60}s)")
    print(f"Saved: {out_path}")


if __name__ == "__main__":
    main()
