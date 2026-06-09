"""
Keep only the 3 most recent episodes, write per-episode JSON sidecars,
and update episodes/index.json.

Usage:
    python scripts/manage_archive.py
"""

import json
import sys
from datetime import date
from pathlib import Path

from mutagen.mp3 import MP3

EPISODES_DIR  = Path("episodes")
INDEX_FILE    = EPISODES_DIR / "index.json"
TMP_DIR       = Path("tmp")
METADATA_FILE = TMP_DIR / "episode_metadata.json"
MAX_EPISODES  = 3


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
        return f"Carmen's Briefing — {d.strftime('%A')} {d.day} {d.strftime('%B')}"
    except ValueError:
        return f"Carmen's Briefing — {filename}"


def _load_tmp_metadata() -> dict | None:
    """Load the metadata written by generate_script.py, if present."""
    if not METADATA_FILE.exists():
        return None
    try:
        return json.loads(METADATA_FILE.read_text(encoding="utf-8"))
    except Exception:
        return None


def _write_sidecar(ep_stem: str, duration: int, title: str, tmp_meta: dict | None):
    """Write episodes/YYYY-MM-DD.json sidecar if not already present."""
    sidecar_path = EPISODES_DIR / f"{ep_stem}.json"
    if sidecar_path.exists():
        try:
            existing = json.loads(sidecar_path.read_text(encoding="utf-8"))
            needs_update = existing.get("duration_seconds", 0) == 0 and duration > 0
            # Overwrite a minimal (empty-story) sidecar if we now have real metadata
            is_minimal = (
                not existing.get("geo_stories") and
                not existing.get("tech_stories") and
                not existing.get("market_stories")
            )
            has_real_meta = tmp_meta and tmp_meta.get("date") == ep_stem
            if needs_update and not has_real_meta:
                existing["duration_seconds"] = duration
                sidecar_path.write_text(
                    json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8"
                )
                print(f"  Updated duration in sidecar → {sidecar_path.name}")
                return
            if not (is_minimal and has_real_meta):
                # Sidecar is fine as-is
                return
        except Exception:
            pass
        # Fall through to overwrite the minimal sidecar with real data

    # Build sidecar from today's tmp metadata (only matches same date)
    if tmp_meta and tmp_meta.get("date") == ep_stem:
        geo = tmp_meta.get("geo_stories") or tmp_meta.get("strategic_stories") or []
        sidecar = {
            "date":             ep_stem,
            "title":            title,
            "duration_seconds": duration,
            "geo_stories":      geo,
            "tech_stories":     tmp_meta.get("tech_stories", []),
            "market_stories":   tmp_meta.get("market_stories", []),
        }
        sidecar_path.write_text(
            json.dumps(sidecar, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(f"  Wrote sidecar → {sidecar_path.name}")
    else:
        # Create a minimal sidecar so the PWA knows the file exists
        sidecar = {
            "date":             ep_stem,
            "title":            title,
            "duration_seconds": duration,
            "geo_stories":      [],
            "market_stories":   [],
        }
        sidecar_path.write_text(
            json.dumps(sidecar, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(f"  Wrote minimal sidecar → {sidecar_path.name} (no tmp metadata matched)")


def main():
    EPISODES_DIR.mkdir(exist_ok=True)

    mp3_files = sorted(
        EPISODES_DIR.glob("*.mp3"),
        key=lambda p: p.name,
        reverse=True,
    )

    # Delete oldest episodes and their sidecars beyond the limit
    to_delete = mp3_files[MAX_EPISODES:]
    for old_file in to_delete:
        print(f"Removing old episode: {old_file.name}")
        old_file.unlink()
        old_sidecar = EPISODES_DIR / f"{old_file.stem}.json"
        if old_sidecar.exists():
            old_sidecar.unlink()
            print(f"  Removed old sidecar: {old_sidecar.name}")

    # Load tmp metadata once (written by generate_script.py today)
    tmp_meta = _load_tmp_metadata()

    # Remaining episodes
    current = sorted(EPISODES_DIR.glob("*.mp3"), key=lambda p: p.name, reverse=True)

    index = []
    for ep in current:
        ep_stem  = ep.stem          # e.g. "2025-01-15"
        duration = episode_duration(ep)
        title    = format_title(ep.name)

        _write_sidecar(ep_stem, duration, title, tmp_meta)

        sidecar_path = EPISODES_DIR / f"{ep_stem}.json"
        index.append({
            "date":             ep_stem,
            "filename":         ep.name,
            "title":            title,
            "duration_seconds": duration,
            "metadata":         f"{ep_stem}.json" if sidecar_path.exists() else None,
        })

    INDEX_FILE.write_text(json.dumps(index, indent=2, ensure_ascii=False))
    print(f"Archive index updated: {len(index)} episodes in {INDEX_FILE}")
    for ep in index:
        meta_flag = "✓" if ep["metadata"] else "—"
        print(f"  {ep['date']} — {ep['duration_seconds']}s — {meta_flag} — {ep['title']}")


if __name__ == "__main__":
    main()
