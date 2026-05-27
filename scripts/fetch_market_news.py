"""
Fetch and score company/markets news from Yahoo Finance RSS and other sources.
Saves scored results to tmp/market_stories.json.

Usage:
    python scripts/fetch_market_news.py [--dry-run]
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import feedparser
import requests

sys.path.insert(0, str(Path(__file__).parent.parent))
from scripts.watchlist import get_all_companies

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"

TMP_DIR = Path("tmp")
OUT_FILE = TMP_DIR / "market_stories.json"

CUTOFF_HOURS = 24

# Supplementary RSS sources keyed by ticker (extend as needed)
EXTRA_RSS = {
    "NVDA": ["https://feeds.reuters.com/reuters/technologyNews"],
    "TSLA": ["https://feeds.reuters.com/reuters/companyNews"],
}


# ── Gemini helper ─────────────────────────────────────────────────────────────

def gemini_call(prompt: str, dry_run: bool = False, retries: int = 4) -> str:
    if dry_run:
        print(f"[DRY-RUN] Gemini prompt ({len(prompt)} chars):\n{prompt[:300]}…\n")
        return ""
    if not GEMINI_API_KEY:
        print("ERROR: GEMINI_API_KEY not set.", file=sys.stderr)
        sys.exit(1)
    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    for attempt in range(1, retries + 1):
        try:
            resp = requests.post(
                GEMINI_URL,
                params={"key": GEMINI_API_KEY},
                json=payload,
                timeout=120,
            )
            if resp.status_code in (429, 503, 529) and attempt < retries:
                wait = 10 * attempt
                print(f"  Gemini {resp.status_code} — retrying in {wait}s (attempt {attempt}/{retries})…")
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp.json()["candidates"][0]["content"]["parts"][0]["text"]
        except requests.exceptions.ReadTimeout:
            if attempt < retries:
                wait = 15 * attempt
                print(f"  Gemini timeout — retrying in {wait}s (attempt {attempt}/{retries})…")
                time.sleep(wait)
            else:
                raise
    raise RuntimeError("Gemini call failed after all retries")


# ── Fetch news for a single company ──────────────────────────────────────────

def fetch_company_news(company: dict, cutoff: datetime) -> list[dict]:
    ticker = company["ticker"]
    name = company["name"]
    exchange = company["exchange"]
    tier = company["tier"]

    articles = []

    # Yahoo Finance RSS — works best for US-listed tickers
    yahoo_url = f"https://finance.yahoo.com/rss/headline?s={ticker}"
    # Korean exchange tickers not supported on Yahoo Finance RSS; skip gracefully
    if exchange in ("KRX",):
        # Fall back to keyword search via Tier 1 Reuters feed results in geo fetch
        pass
    else:
        try:
            feed = feedparser.parse(yahoo_url, request_headers={"User-Agent": "CarmenBriefingBot/1.0"})
            for entry in feed.entries:
                published = None
                if hasattr(entry, "published_parsed") and entry.published_parsed:
                    published = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
                if published and published < cutoff:
                    continue
                headline = getattr(entry, "title", "").strip()
                summary = getattr(entry, "summary", "")[:500].strip()
                if not headline:
                    continue
                articles.append({
                    "company": name,
                    "ticker": ticker,
                    "tier": tier,
                    "headline": headline,
                    "source": "Yahoo Finance",
                    "source_url": getattr(entry, "link", ""),
                    "published_at": published.isoformat() if published else "",
                    "summary_snippet": summary,
                    "score": 0,
                })
        except Exception as e:
            print(f"  WARN: Yahoo Finance RSS failed for {ticker}: {e}", file=sys.stderr)

    # Extra supplementary feeds for select tickers
    for url in EXTRA_RSS.get(ticker, []):
        try:
            feed = feedparser.parse(url, request_headers={"User-Agent": "CarmenBriefingBot/1.0"})
            for entry in feed.entries:
                headline = getattr(entry, "title", "").strip()
                # Only include if company name or ticker mentioned
                if name.lower() not in headline.lower() and ticker.lower() not in headline.lower():
                    continue
                published = None
                if hasattr(entry, "published_parsed") and entry.published_parsed:
                    published = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
                if published and published < cutoff:
                    continue
                summary = getattr(entry, "summary", "")[:500].strip()
                articles.append({
                    "company": name,
                    "ticker": ticker,
                    "tier": tier,
                    "headline": headline,
                    "source": url,
                    "source_url": getattr(entry, "link", ""),
                    "published_at": published.isoformat() if published else "",
                    "summary_snippet": summary,
                    "score": 0,
                })
        except Exception as e:
            print(f"  WARN: Extra RSS failed for {ticker}: {e}", file=sys.stderr)

    return articles


# ── Pre-filter: keep only the N most recent articles per company ──────────────

MAX_ARTICLES_PER_COMPANY = 3  # score at most this many per company

def prefilter_articles(all_articles: list[dict]) -> list[dict]:
    """Keep the MAX_ARTICLES_PER_COMPANY most recent articles per ticker."""
    by_ticker: dict[str, list] = {}
    for a in all_articles:
        by_ticker.setdefault(a["ticker"], []).append(a)
    filtered = []
    for ticker, articles in by_ticker.items():
        # Sort by published_at descending, keep top N
        sorted_arts = sorted(articles, key=lambda x: x.get("published_at", ""), reverse=True)
        filtered.extend(sorted_arts[:MAX_ARTICLES_PER_COMPANY])
    print(f"Pre-filtered to {len(filtered)} articles ({MAX_ARTICLES_PER_COMPANY} max per company).")
    return filtered


# ── Score all company articles (batched) ─────────────────────────────────────

SCORE_BATCH_SIZE = 25

def score_articles(all_articles: list[dict], dry_run: bool = False) -> list[dict]:
    if not all_articles:
        return []

    # Pre-filter before scoring to keep API calls manageable
    all_articles = prefilter_articles(all_articles)

    articles_for_scoring = [
        {"id": i, "company": a["company"], "ticker": a["ticker"],
         "headline": a["headline"], "summary": a["summary_snippet"]}
        for i, a in enumerate(all_articles)
    ]

    score_map: dict[int, int] = {}
    batches = [
        articles_for_scoring[i:i + SCORE_BATCH_SIZE]
        for i in range(0, len(articles_for_scoring), SCORE_BATCH_SIZE)
    ]
    print(f"Scoring {len(all_articles)} articles in {len(batches)} batch(es) of ≤{SCORE_BATCH_SIZE}…")

    for batch_num, batch in enumerate(batches, 1):
        print(f"  Batch {batch_num}/{len(batches)} ({len(batch)} articles)…")
        prompt = (
            "You are a financial news editor. Score each of the following company news articles "
            "for newsworthiness on a scale of 1–10:\n\n"
            "  8–10: Major announcement, earnings surprise, regulatory action, or significant strategic move\n"
            "  5–7:  Notable development, product launch, partnership, or analyst upgrade/downgrade\n"
            "  1–4:  Routine update, minor news, or background coverage\n\n"
            "Return ONLY a valid JSON array. Each object must have exactly:\n"
            '{"id": <int>, "score": <int>}\n\n'
            "Articles:\n"
            + json.dumps(batch, ensure_ascii=False)
        )
        raw = gemini_call(prompt, dry_run)
        if dry_run:
            continue

        raw = raw.strip()
        if raw.startswith("```"):
            raw = "\n".join(raw.splitlines()[1:])
        if raw.endswith("```"):
            raw = "\n".join(raw.splitlines()[:-1])

        try:
            scores = json.loads(raw.strip())
            for s in scores:
                score_map[s["id"]] = s["score"]
        except json.JSONDecodeError as e:
            print(f"  WARN: Failed to parse batch {batch_num} scores ({e}) — skipping batch.", file=sys.stderr)

    if dry_run:
        return all_articles

    for i, a in enumerate(all_articles):
        a["score"] = score_map.get(i, 5)  # default 5 if batch failed

    return all_articles


# ── Per-company best story selection ─────────────────────────────────────────

def select_best_per_company(all_articles: list[dict]) -> list[dict]:
    """Keep only the highest-scoring article per company."""
    by_company: dict[str, list] = {}
    for a in all_articles:
        by_company.setdefault(a["ticker"], []).append(a)
    best = []
    for ticker, articles in by_company.items():
        top = max(articles, key=lambda x: x["score"])
        best.append(top)  # always include best story per company
    return best


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    TMP_DIR.mkdir(exist_ok=True)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=CUTOFF_HOURS)

    companies = get_all_companies()
    all_articles = []

    print(f"Fetching news for {len(companies)} companies…")
    for company in companies:
        articles = fetch_company_news(company, cutoff)
        all_articles.extend(articles)
        if articles:
            print(f"  {company['ticker']}: {len(articles)} articles")

    print(f"Total: {len(all_articles)} company articles. Scoring with Gemini…")
    all_articles = score_articles(all_articles, args.dry_run)
    best = select_best_per_company(all_articles)

    OUT_FILE.write_text(json.dumps(best, indent=2, ensure_ascii=False))
    print(f"Saved {len(best)} company stories → {OUT_FILE}")

    if args.dry_run:
        print("\n[DRY-RUN] Best company stories (unscored):")
        for s in best[:10]:
            print(f"  [Tier {s['tier']}] {s['ticker']}: {s['headline'][:70]}")


if __name__ == "__main__":
    main()
