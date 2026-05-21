"""
Keep only the 3 most recent episodes and update episodes/index.json.

Usage:
    python scripts/manage_archive.py
"""

import json
import sys
from datetime import date
from pathlib import Path

from mutagen.mp3 import MP3

EPISODES_DIR = Path("episodes")
INDEX_FILE = EPISODES_DIR / "index.json"
MAX_EPISODES = 3


def episode_duration(path: Path) -> int:
    """Return duration in seconds using mutagen."""
    try:
        audio = MP3(str(path))
        return int(audio.info.length)
    except Exception:
        return 0


def format_title(filename: str) -> str:
    """Turn '2025-01-15.mp3' into 'Carmen's Briefing — Wednesday 15 January'."""
    try:
        d = date.fromisoformat(filename.replace(".mp3", ""))
        return f"Carmen's Briefing — {d.strftime('%A %-d %B')}"
    except ValueError:
        return f"Carmen's Briefing — {filename}"


def main():
    EPISODES_DIR.mkdir(exist_ok=True)

    mp3_files = sorted(
        EPISODES_DIR.glob("*.mp3"),
        key=lambda p: p.name,
        reverse=True,
    )

    # Delete oldest episodes beyond the limit
    to_delete = mp3_files[MAX_EPISODES:]
    for old_file in to_delete:
        print(f"Removing old episode: {old_file.name}")
        old_file.unlink()

    # Remaining episodes
    current = sorted(EPISODES_DIR.glob("*.mp3"), key=lambda p: p.name, reverse=True)

    index = []
    for ep in current:
        entry_date = ep.stem  # e.g. "2025-01-15"
        duration = episode_duration(ep)
        index.append({
            "date": entry_date,
            "filename": ep.name,
            "title": format_title(ep.name),
            "duration_seconds": duration,
        })

    INDEX_FILE.write_text(json.dumps(index, indent=2, ensure_ascii=False))
    print(f"Archive index updated: {len(index)} episodes in {INDEX_FILE}")
    for ep in index:
        print(f"  {ep['date']} — {ep['duration_seconds']}s — {ep['title']}")


if __name__ == "__main__":
    main()
