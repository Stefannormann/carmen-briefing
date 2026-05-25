"""
Fetch, filter, score, and select geopolitical news stories.
Saves selected stories to tmp/geo_stories.json.

Usage:
    python scripts/fetch_geo_news.py [--dry-run]
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

# Allow imports from project root
sys.path.insert(0, str(Path(__file__).parent.parent))
from config.geo_sources import (
    GEO_RSS_TIER_1, GEO_RSS_TIER_2, DANISH_LANGUAGE_SOURCES,
    GEO_TOPIC_TIER_1, GEO_TOPIC_TIER_2,
)
from config.geo_keywords import GEO_KEYWORDS
from scripts.watchlist import get_all_names

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"

TMP_DIR = Path("tmp")
OUT_FILE = TMP_DIR / "geo_stories.json"

CUTOFF_HOURS = 24
MAX_GEO_STORIES = 3
MIN_TIER1_SCORE = 5


# ── Gemini helper ─────────────────────────────────────────────────────────────

def gemini_call(prompt: str, dry_run: bool = False) -> str:
    if dry_run:
        print(f"[DRY-RUN] Gemini prompt ({len(prompt)} chars):\n{prompt[:300]}…\n")
        return ""
    if not GEMINI_API_KEY:
        print("ERROR: GEMINI_API_KEY not set.", file=sys.stderr)
        sys.exit(1)
    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    resp = requests.post(
        GEMINI_URL,
        params={"key": GEMINI_API_KEY},
        json=payload,
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()["candidates"][0]["content"]["parts"][0]["text"]


# ── Step 1: Fetch RSS ─────────────────────────────────────────────────────────

def fetch_feeds(dry_run: bool = False) -> list[dict]:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=CUTOFF_HOURS)
    articles = []

    def parse_feed(url: str, feed_tier: int):
        try:
            feed = feedparser.parse(url, request_headers={"User-Agent": "CarmenBriefingBot/1.0"})
        except Exception as e:
            print(f"  WARN: failed to fetch {url}: {e}", file=sys.stderr)
            return
        for entry in feed.entries:
            published = None
            if hasattr(entry, "published_parsed") and entry.published_parsed:
                published = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
            elif hasattr(entry, "updated_parsed") and entry.updated_parsed:
                published = datetime(*entry.updated_parsed[:6], tzinfo=timezone.utc)
            if published and published < cutoff:
                continue
            headline = getattr(entry, "title", "").strip()
            summary = getattr(entry, "summary", "")[:500].strip()
            link = getattr(entry, "link", "")
            if not headline:
                continue
            articles.append({
                "headline": headline,
                "summary_snippet": summary,
                "source_url": link,
                "feed_url": url,
                "feed_tier": feed_tier,
                "published_at": published.isoformat() if published else "",
                "topic": [],
                "score": 0,
                "watchlist_flag": False,
                "watchlist_note": "",
            })

    print("Fetching Tier 1 RSS feeds…")
    for url in GEO_RSS_TIER_1:
        parse_feed(url, 1)

    print("Fetching Tier 2 RSS feeds…")
    for url in GEO_RSS_TIER_2:
        parse_feed(url, 2)

    print(f"Fetched {len(articles)} articles within past {CUTOFF_HOURS}h.")
    return articles


# ── Step 2: Deduplicate ───────────────────────────────────────────────────────

def _words(text: str) -> list[str]:
    return text.lower().split()

def _shared_consecutive(a: str, b: str, n: int = 6) -> bool:
    wa, wb = _words(a), _words(b)
    seq_a = [" ".join(wa[i:i+n]) for i in range(len(wa)-n+1)]
    text_b = " ".join(wb)
    return any(s in text_b for s in seq_a)

def deduplicate(articles: list[dict]) -> list[dict]:
    kept = []
    for article in sorted(articles, key=lambda x: x["feed_tier"]):
        duplicate = False
        for existing in kept:
            if _shared_consecutive(article["headline"], existing["headline"]):
                duplicate = True
                break
        if not duplicate:
            kept.append(article)
    print(f"After deduplication: {len(kept)} articles.")
    return kept


# ── Step 3: Translate Danish ──────────────────────────────────────────────────

def translate_danish(articles: list[dict], dry_run: bool = False) -> list[dict]:
    danish_articles = [a for a in articles if a["feed_url"] in DANISH_LANGUAGE_SOURCES]
    if not danish_articles:
        return articles
    print(f"Translating {len(danish_articles)} Danish articles…")
    for a in danish_articles:
        prompt = (
            "Translate the following Danish news headline and summary to English.\n"
            "Return only the translated text in this exact format:\n"
            "HEADLINE: <translated headline>\nSUMMARY: <translated summary>\n\n"
            f"Headline: {a['headline']}\nSummary: {a['summary_snippet']}"
        )
        raw = gemini_call(prompt, dry_run)
        if raw:
            lines = raw.strip().splitlines()
            for line in lines:
                if line.startswith("HEADLINE:"):
                    a["headline"] = line.replace("HEADLINE:", "").strip()
                elif line.startswith("SUMMARY:"):
                    a["summary_snippet"] = line.replace("SUMMARY:", "").strip()
    return articles


# ── Step 4: Keyword topic tagging ─────────────────────────────────────────────

def tag_topics(articles: list[dict]) -> list[dict]:
    for a in articles:
        text = (a["headline"] + " " + a["summary_snippet"]).lower()
        matched = [topic for topic, kws in GEO_KEYWORDS.items() if any(kw in text for kw in kws)]
        a["topic"] = matched if matched else ["other"]
    return articles


# ── Step 5: Gemini scoring ────────────────────────────────────────────────────

def score_articles(articles: list[dict], dry_run: bool = False) -> list[dict]:
    watchlist_companies = ", ".join(get_all_names())
    articles_for_scoring = [
        {"id": i, "headline": a["headline"], "summary": a["summary_snippet"]}
        for i, a in enumerate(articles)
    ]
    prompt = (
        "You are a geopolitical news editor. Score each of the following articles "
        "for newsworthiness on a scale of 1–10:\n\n"
        "  8–10: Major policy shift, diplomatic incident, or significant geopolitical move\n"
        "  5–7:  Notable escalation, development, or policy statement worth tracking\n"
        "  1–4:  Routine update, minor statement, or background noise\n\n"
        "For each article also assess:\n"
        f"- watchlist_flag: true if the story has direct relevance to any of these companies: {watchlist_companies}\n"
        "- watchlist_note: if watchlist_flag is true, one sentence explaining the company relevance\n\n"
        "Return ONLY a valid JSON array. Each object must have exactly:\n"
        '{"id": <int>, "score": <int>, "watchlist_flag": <bool>, "watchlist_note": <string>}\n\n'
        "Articles:\n"
        + json.dumps(articles_for_scoring, ensure_ascii=False)
    )
    raw = gemini_call(prompt, dry_run)
    if dry_run:
        return articles

    # Strip markdown code fences if present
    raw = raw.strip()
    if raw.startswith("```"):
        raw = "\n".join(raw.splitlines()[1:])
    if raw.endswith("```"):
        raw = "\n".join(raw.splitlines()[:-1])

    try:
        scores = json.loads(raw.strip())
    except json.JSONDecodeError as e:
        print(f"ERROR: Failed to parse Gemini scoring response: {e}", file=sys.stderr)
        print(f"Raw response: {raw[:500]}", file=sys.stderr)
        sys.exit(1)

    score_map = {s["id"]: s for s in scores}
    for i, a in enumerate(articles):
        if i in score_map:
            a["score"] = score_map[i].get("score", 0)
            a["watchlist_flag"] = score_map[i].get("watchlist_flag", False)
            a["watchlist_note"] = score_map[i].get("watchlist_note", "")
    return articles


# ── Step 6: Story selection ───────────────────────────────────────────────────

def select_stories(articles: list[dict]) -> list[dict]:
    sorted_articles = sorted(articles, key=lambda x: -x["score"])

    selected = []
    covered_topics = set()

    # Prefer Tier 1 topic coverage first
    tier1_topics = set(GEO_TOPIC_TIER_1)
    tier2_topics = set(GEO_TOPIC_TIER_2)

    def pick(candidates, min_score=0):
        for a in candidates:
            if len(selected) >= MAX_GEO_STORIES:
                break
            if a["score"] < min_score:
                continue
            topics = set(a["topic"])
            # Avoid same-topic duplicates unless both score >= 8
            overlap = topics & covered_topics
            if overlap and a["score"] < 8:
                continue
            selected.append(a)
            covered_topics.update(topics)

    # Pass 1: high-scoring tier1 topic stories
    tier1_candidates = [a for a in sorted_articles if set(a["topic"]) & tier1_topics]
    pick(tier1_candidates, min_score=MIN_TIER1_SCORE)

    # Pass 2: fill remaining slots from all articles (including tier2 topics)
    pick(sorted_articles, min_score=1)

    print(f"Selected {len(selected)} geopolitical stories.")
    return selected


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="Skip Gemini calls; print what would be sent instead.")
    args = parser.parse_args()

    TMP_DIR.mkdir(exist_ok=True)

    articles = fetch_feeds(args.dry_run)
    articles = deduplicate(articles)
    articles = translate_danish(articles, args.dry_run)
    articles = tag_topics(articles)
    articles = score_articles(articles, args.dry_run)
    selected = select_stories(articles)

    OUT_FILE.write_text(json.dumps(selected, indent=2, ensure_ascii=False))
    print(f"Saved {len(selected)} stories → {OUT_FILE}")

    if args.dry_run:
        print("\n[DRY-RUN] Selected stories (unscored):")
        for s in selected:
            print(f"  [{s['feed_tier']}] {s['headline'][:80]}")


if __name__ == "__main__":
    main()
