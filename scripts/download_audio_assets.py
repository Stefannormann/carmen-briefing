"""
Download intro jingle and transition tone from Freesound CDN.
Idempotent — skips download if files already exist.

Audio assets (both CC0 / public domain):
  Jingle:     "Podcast Jingle" by plasterbrain  — freesound.org/s/273159/
  Transition: "Thin Bell Ding 3" by Khrinx      — freesound.org/s/333694/

Usage:
    python scripts/download_audio_assets.py
"""

import sys
from pathlib import Path

import requests
from pydub import AudioSegment

AUDIO_DIR = Path("audio")

# Direct CDN preview URLs — no API key required.
# These are the publicly accessible MP3 previews from the Freesound CDN.
ASSETS = [
    {
        "label": "Intro jingle",
        "url": "https://cdn.freesound.org/previews/273/273159_4284968-hq.mp3",
        "fallback_url": "https://cdn.freesound.org/previews/273/273159_4284968-lq.mp3",
        "out_path": AUDIO_DIR / "jingle.mp3",
        "attribution": "Podcast Jingle by plasterbrain — freesound.org/s/273159/ (CC0)",
    },
    {
        "label": "Transition tone",
        "url": "https://cdn.freesound.org/previews/333/333694_1187042-hq.mp3",
        "fallback_url": "https://cdn.freesound.org/previews/333/333694_1187042-lq.mp3",
        "out_path": AUDIO_DIR / "transition.mp3",
        "attribution": "Thin Bell Ding 3 by Khrinx — freesound.org/s/333694/ (CC0)",
    },
]


def download_asset(asset: dict) -> bool:
    out_path: Path = asset["out_path"]

    if out_path.exists():
        print(f"  EXISTS: {asset['label']} already at {out_path} — skipping.")
        return True

    out_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"  Downloading {asset['label']}…")
    print(f"    {asset['attribution']}")

    for url in [asset["url"], asset["fallback_url"]]:
        try:
            resp = requests.get(url, stream=True, timeout=30,
                                headers={"User-Agent": "CarmenBriefingBot/1.0"})
            resp.raise_for_status()

            raw_path = out_path.with_suffix(".tmp")
            with raw_path.open("wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    f.write(chunk)

            # Normalise to MP3 via pydub (in case format differs)
            try:
                audio = AudioSegment.from_file(str(raw_path))
                audio.export(str(out_path), format="mp3", bitrate="128k")
                raw_path.unlink()
            except Exception:
                raw_path.rename(out_path)  # keep as-is if already MP3

            print(f"    → Saved to {out_path}")
            return True

        except Exception as e:
            print(f"    WARN: {url} failed ({e}) — trying fallback…")

    print(f"  ERROR: Could not download {asset['label']}.", file=sys.stderr)
    return False


def main():
    print("Downloading Freesound audio assets…")
    results = [download_asset(a) for a in ASSETS]

    if all(results):
        print("\nAll audio assets ready.")
    else:
        failed = [a["label"] for a, ok in zip(ASSETS, results) if not ok]
        print(f"\nERROR: Failed to download: {failed}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
