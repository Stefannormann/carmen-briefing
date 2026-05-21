"""
Download intro jingle and transition tone from Freesound.org.
Idempotent — skips download if files already exist.

SETUP: Replace the placeholder sound IDs below with real Freesound IDs.
       Browse https://freesound.org, filter by CC0 licence, and paste the ID
       from the URL (e.g. https://freesound.org/s/123456/ → ID is 123456).

Usage:
    python scripts/download_audio_assets.py
"""

import os
import sys
from pathlib import Path

import requests
from pydub import AudioSegment

AUDIO_DIR = Path("audio")

# ── Freesound configuration ───────────────────────────────────────────────────
# Replace these placeholder IDs with your chosen Freesound sound IDs.
# You can find a sound's ID in its URL: freesound.org/s/<ID>/
#
# Recommended search: filter by "CC0" licence for zero-restriction use.
#   Jingle:     search "news jingle" or "broadcast intro" — pick ~5–10 sec clip
#   Transition: search "transition tone" or "ding" — pick ~1–2 sec clip

JINGLE_SOUND_ID     = "273159"   # "Podcast Jingle" by plasterbrain — 6s, CC0
TRANSITION_SOUND_ID = "333694"   # "Thin Bell Ding 3" by Khrinx — 1.86s, CC0

# Freesound API key — optional for anonymous preview downloads.
# For full-quality downloads, get a free API key at freesound.org/apiv2/apply/
# and set env var FREESOUND_API_KEY, or leave blank to use preview quality.
FREESOUND_API_KEY = os.environ.get("FREESOUND_API_KEY", "")

ASSETS = [
    {
        "sound_id": JINGLE_SOUND_ID,
        "out_path": AUDIO_DIR / "jingle.mp3",
        "label": "Intro jingle",
    },
    {
        "sound_id": TRANSITION_SOUND_ID,
        "out_path": AUDIO_DIR / "transition.mp3",
        "label": "Transition tone",
    },
]


def download_freesound(sound_id: str, out_path: Path, label: str) -> None:
    if sound_id.startswith("YOUR_"):
        print(f"  SKIP: {label} — placeholder ID not set.")
        print(f"        Edit JINGLE_SOUND_ID / TRANSITION_SOUND_ID in this file.")
        return

    if out_path.exists():
        print(f"  EXISTS: {label} already at {out_path} — skipping.")
        return

    print(f"  Downloading {label} (Freesound ID: {sound_id})…")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if FREESOUND_API_KEY:
        # Full-quality authenticated download
        info_url = f"https://freesound.org/apiv2/sounds/{sound_id}/"
        info = requests.get(info_url, params={"token": FREESOUND_API_KEY}, timeout=30)
        info.raise_for_status()
        download_url = info.json()["download"]
        resp = requests.get(download_url, params={"token": FREESOUND_API_KEY},
                            stream=True, timeout=60)
    else:
        # Low-quality preview (128kbps MP3) — no API key needed
        preview_url = f"https://freesound.org/apiv2/sounds/{sound_id}/"
        info = requests.get(preview_url, timeout=30)
        info.raise_for_status()
        previews = info.json().get("previews", {})
        preview_mp3 = previews.get("preview-hq-mp3") or previews.get("preview-lq-mp3")
        if not preview_mp3:
            print(f"  ERROR: No preview URL found for sound {sound_id}", file=sys.stderr)
            return
        resp = requests.get(preview_mp3, stream=True, timeout=60)

    resp.raise_for_status()
    raw_path = out_path.with_suffix(".tmp")
    with raw_path.open("wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            f.write(chunk)

    # Convert to MP3 via pydub (handles wav/ogg/flac → mp3)
    try:
        audio = AudioSegment.from_file(str(raw_path))
        audio.export(str(out_path), format="mp3", bitrate="128k")
        raw_path.unlink()
        print(f"    → Saved to {out_path}")
    except Exception as e:
        raw_path.rename(out_path)  # keep as-is if conversion fails
        print(f"    → Saved raw (conversion skipped: {e})")


def main():
    print("Downloading Freesound audio assets…")
    for asset in ASSETS:
        download_freesound(asset["sound_id"], asset["out_path"], asset["label"])

    # Check final state
    missing = [a for a in ASSETS if not a["out_path"].exists()]
    if missing:
        missing_labels = [a["label"] for a in missing]
        print(f"\nNOTE: Missing audio assets: {missing_labels}")
        print("      Set the Freesound sound IDs in this file and re-run.")
    else:
        print("\nAll audio assets ready.")


if __name__ == "__main__":
    main()
