"""
Stock watchlist with tier assignments and prioritisation logic.

Companies are loaded from filters.json if present (runtime config editable
via the REST API), otherwise fall back to the WATCHLIST constant below.
Edit WATCHLIST to change the hardcoded defaults / re-run create_filters_json.py.
"""

import json
from pathlib import Path

WATCHLIST = {
    "tier1": [
        {"name": "NVIDIA",    "ticker": "NVDA",   "exchange": "NASDAQ"},
        {"name": "Alphabet",  "ticker": "GOOGL",  "exchange": "NASDAQ"},
        {"name": "Tesla",     "ticker": "TSLA",   "exchange": "NASDAQ"},
        {"name": "Microsoft", "ticker": "MSFT",   "exchange": "NASDAQ"},
        {"name": "IREN",      "ticker": "IREN",   "exchange": "NASDAQ"},
        {"name": "Cipher Mining", "ticker": "CIFR", "exchange": "NASDAQ"},
        {"name": "TSMC",      "ticker": "TSM",    "exchange": "NYSE"},
        {"name": "Palantir",  "ticker": "PLTR",   "exchange": "NASDAQ"},
        {"name": "OpenAI",    "ticker": "OPENAI", "exchange": "PRIVATE"},
        {"name": "Anthropic", "ticker": "ANTH",   "exchange": "PRIVATE"},
        {"name": "SpaceX",    "ticker": "SPACEX", "exchange": "PRIVATE"},
    ],
    "tier2": [
        {"name": "CoreWeave",   "ticker": "CRWV",  "exchange": "NASDAQ"},
        {"name": "Nebius",      "ticker": "NBIS",  "exchange": "NASDAQ"},
        {"name": "Meta",        "ticker": "META",  "exchange": "NASDAQ"},
        {"name": "Amazon",      "ticker": "AMZN",  "exchange": "NASDAQ"},
        {"name": "Apple",       "ticker": "AAPL",  "exchange": "NASDAQ"},
        {"name": "Robinhood",   "ticker": "HOOD",  "exchange": "NASDAQ"},
        {"name": "Circle",      "ticker": "CRCL",  "exchange": "NYSE"},
        {"name": "Coinbase",    "ticker": "COIN",  "exchange": "NASDAQ"},
        {"name": "SK Hynix",    "ticker": "000660","exchange": "KRX"},
        {"name": "Micron",      "ticker": "MU",    "exchange": "NASDAQ"},
        {"name": "Samsung",     "ticker": "005930","exchange": "KRX"},
        {"name": "Broadcom",    "ticker": "AVGO",  "exchange": "NASDAQ"},
        {"name": "ASML",        "ticker": "ASML",  "exchange": "NASDAQ"},
        {"name": "Snowflake",   "ticker": "SNOW",  "exchange": "NYSE"},
        {"name": "Salesforce",  "ticker": "CRM",   "exchange": "NYSE"},
    ],
    "tier3": [
        {"name": "MP Materials",             "ticker": "MP",    "exchange": "NYSE"},
        {"name": "USA Rare Earth",           "ticker": "USAR",  "exchange": "OTC"},
        {"name": "Critical Metals",          "ticker": "CRTM",  "exchange": "OTC"},
        {"name": "United States Antimony",   "ticker": "UAMY",  "exchange": "NYSE American"},
        {"name": "EOS Energy",               "ticker": "EOSE",  "exchange": "NASDAQ"},
        {"name": "Fluence Energy",           "ticker": "FLNC",  "exchange": "NASDAQ"},
        {"name": "American Battery Technologies", "ticker": "ABAT", "exchange": "NASDAQ"},
        {"name": "Enovix",                   "ticker": "ENVX",  "exchange": "NASDAQ"},
        {"name": "Galaxy Digital",           "ticker": "GLXY",  "exchange": "NASDAQ"},
        {"name": "CrowdStrike",              "ticker": "CRWD",  "exchange": "NASDAQ"},
        {"name": "Cloudflare",               "ticker": "NET",   "exchange": "NYSE"},
        {"name": "ServiceNow",               "ticker": "NOW",   "exchange": "NYSE"},
        {"name": "Astera Labs",              "ticker": "ALAB",  "exchange": "NASDAQ"},
        {"name": "AST SpaceMobile",          "ticker": "ASTS",  "exchange": "NASDAQ"},
        {"name": "Rocket Lab",               "ticker": "RKLB",  "exchange": "NASDAQ"},
        {"name": "Planet Labs",              "ticker": "PL",    "exchange": "NYSE"},
    ],
}

_FILTERS_CANDIDATES = [
    Path("filters.json"),
    Path("/opt/carmen/filters.json"),
]


def _load_filters_companies() -> dict | None:
    """Return companies dict from filters.json if available, else None."""
    for path in _FILTERS_CANDIDATES:
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                companies = data.get("companies")
                if companies and all(k in companies for k in ("tier1", "tier2", "tier3")):
                    return companies
            except Exception:
                pass
    return None


def _active_watchlist() -> dict:
    """Return active company dict (filters.json preferred, hardcoded fallback)."""
    return _load_filters_companies() or WATCHLIST


# Flat list of all companies with tier annotation, in priority order
def get_all_companies():
    result = []
    for tier_name, companies in _active_watchlist().items():
        tier_num = int(tier_name.replace("tier", ""))
        for c in companies:
            result.append({**c, "tier": tier_num})
    return result


def prioritise_stories(scored_stories: list[dict]) -> list[dict]:
    """
    Sort company news stories applying tier priority + traffic exception.

    scored_stories: list of dicts, each must have:
        - ticker (str)
        - tier (int)
        - score (int 1-10, Gemini newsworthiness)

    Returns sorted list, highest priority first.

    Traffic exception: a Tier 2/3 company with score >= 8 is promoted
    above Tier 1 companies whose score <= 5.
    """
    def sort_key(story):
        tier = story.get("tier", 3)
        score = story.get("score", 5)
        # Tier 1 normally scores with a large tier bonus
        tier_bonus = (4 - tier) * 10  # tier1=30, tier2=20, tier3=10
        # Traffic exception: high-traffic lower-tier story promoted
        if tier > 1 and score >= 8:
            tier_bonus = 25  # bumps above quiet tier1 (10+score<=15)
        return -(tier_bonus + score)

    return sorted(scored_stories, key=sort_key)


def get_all_tickers() -> list[str]:
    """Return all tickers as a flat list (used for Gemini prompts)."""
    return [c["ticker"] for c in get_all_companies()]


def get_all_names() -> list[str]:
    """Return all company names (used for Gemini prompts)."""
    return [c["name"] for c in get_all_companies()]
