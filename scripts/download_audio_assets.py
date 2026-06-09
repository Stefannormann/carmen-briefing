"""
Download intro jingle and transition tone from Freesound.
Idempotent — skips download if files already exist.

Audio assets (both CC0 / public domain):
  Jingle:     "Podcast Jingle" by plasterbrain  — freesound.org/s/273159/
  Transition: "Thin Bell Ding 3" by Khrinx      — freesound.org/s/333694/

Usage:
    FREESOUND_API_KEY=<key> python scripts/download_audio_assets.py
"""

import os
import sys
from pathlib import Path

import requests

AUDIO_DIR = Path("audio")

ASSETS = [
    {
        "label": "Intro jingle",
        "sound_id": 273159,
        "out_path": AUDIO_DIR / "jingle.mp3",
        "attribution": "Podcast Jingle by plasterbrain — freesound.org/s/273159/ (CC0)",
    },
    {
        "label": "Transition tone",
        "sound_id": 333694,
        "out_path": AUDIO_DIR / "transition.mp3",
        "attribution": "Thin Bell Ding 3 by Khrinx — freesound.org/s/333694/ (CC0)",
    },
]


def get_preview_urls(sound_id: int, api_key: str) -> list[str]:
    """Fetch sound info from Freesound API and return preview MP3 URLs."""
    url = f"https://freesound.org/apiv2/sounds/{sound_id}/"
    resp = requests.get(url, params={"token": api_key}, timeout=15,
                        headers={"User-Agent": "CarmenBriefingBot/1.0"})
    resp.raise_for_status()
    data = resp.json()
    previews = data.get("previews", {})
    urls = []
    for key in ("preview-hq-mp3", "preview-lq-mp3"):
        if key in previews:
            urls.append(previews[key])
    return urls


def download_asset(asset: dict, api_key: str | None) -> bool:
    out_path: Path = asset["out_path"]

    if out_path.exists():
        print(f"  EXISTS: {asset['label']} already at {out_path} — skipping.")
        return True

    out_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"  Downloading {asset['label']}…")
    print(f"    {asset['attribution']}")

    urls = []

    # Prefer API-resolved preview URLs (authenticated, not CDN-blocked)
    if api_key:
        try:
            urls = get_preview_urls(asset["sound_id"], api_key)
        except Exception as e:
            print(f"    WARN: Freesound API lookup failed ({e}) — falling back to CDN URLs.")

    # Fallback: direct CDN guesses (may be blocked without auth)
    if not urls:
        sid = asset["sound_id"]
        urls = [
            f"https://cdn.freesound.org/previews/{sid // 1000}/{sid}_*.mp3",
        ]
        # For known IDs, use the confirmed CDN paths
        cdn_fallbacks = {
            273159: [
                "https://cdn.freesound.org/previews/273/273159_4284968-hq.mp3",
                "https://cdn.freesound.org/previews/273/273159_4284968-lq.mp3",
            ],
            333694: [
                "https://cdn.freesound.org/previews/333/333694_1187042-hq.mp3",
                "https://cdn.freesound.org/previews/333/333694_1187042-lq.mp3",
            ],
        }
        urls = cdn_fallbacks.get(sid, [])

    for url in urls:
        try:
            resp = requests.get(url, stream=True, timeout=30,
                                headers={"User-Agent": "CarmenBriefingBot/1.0"})
            resp.raise_for_status()

            with out_path.open("wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    f.write(chunk)

            print(f"    -> Saved to {out_path}")
            return True

        except Exception as e:
            print(f"    WARN: {url} failed ({e}) — trying next URL…")

    print(f"  ERROR: Could not download {asset['label']}.", file=sys.stderr)
    return False


def main():
    api_key = os.environ.get("FREESOUND_API_KEY")
    if not api_key:
        print("  WARN: FREESOUND_API_KEY not set — will attempt unauthenticated CDN download.")

    print("Downloading Freesound audio assets…")
    results = [download_asset(a, api_key) for a in ASSETS]

    if all(results):
        print("\nAll audio assets ready.")
    else:
        failed = [a["label"] for a, ok in zip(ASSETS, results) if not ok]
        print(f"\nERROR: Failed to download: {failed}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
