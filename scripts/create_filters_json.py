"""
Initialise filters.json from the hardcoded config files.

Writes filters.json to the current directory (run from /opt/carmen on server,
or from the project root locally).  Safe to re-run — will NOT overwrite an
existing file unless --force is passed.

Usage:
    python scripts/create_filters_json.py [--force] [--output PATH]
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from config.geo_sources import GEO_RSS_TIER_1, GEO_RSS_TIER_2
from config.geo_keywords import STRATEGIC_KEYWORDS, TECH_KEYWORDS
from scripts.watchlist import WATCHLIST

DEFAULT_OUTPUT = Path("filters.json")


def build_filters() -> dict:
    return {
        "version": 1,
        "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "geo_sources": {
            "tier1": GEO_RSS_TIER_1,
            "tier2": GEO_RSS_TIER_2,
        },
        "strategic_keywords": STRATEGIC_KEYWORDS,
        "tech_keywords": TECH_KEYWORDS,
        "companies": WATCHLIST,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force", action="store_true",
        help="Overwrite existing filters.json",
    )
    parser.add_argument(
        "--output", type=Path, default=DEFAULT_OUTPUT,
        help=f"Output path (default: {DEFAULT_OUTPUT})",
    )
    args = parser.parse_args()

    if args.output.exists() and not args.force:
        print(f"filters.json already exists at {args.output} — skipping.")
        print("Pass --force to overwrite.")
        sys.exit(0)

    filters = build_filters()
    args.output.write_text(json.dumps(filters, indent=2, ensure_ascii=False))
    action = "Overwrote" if args.output.exists() else "Created"
    keyword_count = (
        sum(len(v) for v in filters["strategic_keywords"].values())
        + sum(len(v) for v in filters["tech_keywords"].values())
    )
    print(f"{action} {args.output} ({len(filters['companies']['tier1'])} T1, "
          f"{len(filters['companies']['tier2'])} T2, "
          f"{len(filters['companies']['tier3'])} T3 companies; "
          f"{keyword_count} keywords; "
          f"{len(filters['geo_sources']['tier1']) + len(filters['geo_sources']['tier2'])} RSS feeds)")


if __name__ == "__main__":
    main()
