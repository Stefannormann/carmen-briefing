"""
Fetch and score company/markets news from Yahoo Finance RSS and other sources.

Two-gate selection system:
  Gate 1 – company name / ticker present in article (implicit via Yahoo Finance RSS)
  Gate 2 – composite popularity score:
            0.35 * social    (Reddit upvotes + HN points, normalised)
          + 0.15 * authority (publisher domain reputation)
          + 0.25 * coverage  (TF-IDF cluster size across all company articles)
          + 0.15 * trend     (flat 0.50 — pytrends dropped)
          + 0.10 * recency   (exponential decay, 12-hour half-life)

Saves scored results to tmp/market_stories.json.

Usage:
    python scripts/fetch_market_news.py [--dry-run]
"""

import argparse
import json
import math
import os
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import feedparser
import requests

sys.path.insert(0, str(Path(__file__).parent.parent))
from scripts.watchlist import get_all_companies
from config.publisher_authority import get_authority

# ── Reddit subreddits for market / company news ───────────────────────────────
MARKET_REDDIT_SUBS = ["investing", "stocks", "finance", "wallstreetbets"]

# ── Config ────────────────────────────────────────────────────────────────────
TMP_DIR = Path("tmp")
OUT_FILE = TMP_DIR / "market_stories.json"

CUTOFF_HOURS            = 24
MAX_ARTICLES_PER_COMPANY = 5   # fetch up to this many before popularity filtering
SIM_THRESHOLD           = 0.65

# Composite score weights
W_SOCIAL    = 0.35
W_AUTHORITY = 0.15
W_COVERAGE  = 0.25
W_TREND     = 0.15
W_RECENCY   = 0.10
TREND_SCORE = 0.50

SOCIAL_NOT_FOUND = 0.20

# Supplementary RSS sources keyed by ticker
EXTRA_RSS = {
    "NVDA": ["https://feeds.reuters.com/reuters/technologyNews"],
    "TSLA": ["https://feeds.reuters.com/reuters/companyNews"],
}


# ── Fetch news for a single company ──────────────────────────────────────────

def fetch_company_news(company: dict, cutoff: datetime) -> list[dict]:
    ticker   = company["ticker"]
    name     = company["name"]
    exchange = company["exchange"]
    tier     = company["tier"]
    articles = []

    # Yahoo Finance RSS — best for US-listed tickers
    # KRX (Korean exchange) tickers are not supported on Yahoo Finance RSS
    if exchange not in ("KRX",):
        yahoo_url = f"https://finance.yahoo.com/rss/headline?s={ticker}"
        try:
            feed = feedparser.parse(
                yahoo_url, request_headers={"User-Agent": "CarmenBriefingBot/1.0"}
            )
            for entry in feed.entries:
                published = None
                if hasattr(entry, "published_parsed") and entry.published_parsed:
                    published = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
                if published and published < cutoff:
                    continue
                headline = getattr(entry, "title", "").strip()
                summary  = getattr(entry, "summary", "")[:500].strip()
                if not headline:
                    continue
                articles.append({
                    "company":         name,
                    "ticker":          ticker,
                    "tier":            tier,
                    "headline":        headline,
                    "source":          "Yahoo Finance",
                    "source_url":      getattr(entry, "link", ""),
                    "published_at":    published.isoformat() if published else "",
                    "summary_snippet": summary,
                    "score":           5,
                })
        except Exception as e:
            print(f"  WARN: Yahoo Finance RSS failed for {ticker}: {e}", file=sys.stderr)

    # Extra supplementary feeds for select tickers
    for url in EXTRA_RSS.get(ticker, []):
        try:
            feed = feedparser.parse(
                url, request_headers={"User-Agent": "CarmenBriefingBot/1.0"}
            )
            for entry in feed.entries:
                headline = getattr(entry, "title", "").strip()
                # Only include if company name or ticker is mentioned
                if (name.lower() not in headline.lower()
                        and ticker.lower() not in headline.lower()):
                    continue
                published = None
                if hasattr(entry, "published_parsed") and entry.published_parsed:
                    published = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
                if published and published < cutoff:
                    continue
                summary = getattr(entry, "summary", "")[:500].strip()
                articles.append({
                    "company":         name,
                    "ticker":          ticker,
                    "tier":            tier,
                    "headline":        headline,
                    "source":          url,
                    "source_url":      getattr(entry, "link", ""),
                    "published_at":    published.isoformat() if published else "",
                    "summary_snippet": summary,
                    "score":           5,
                })
        except Exception as e:
            print(f"  WARN: Extra RSS failed for {ticker}: {e}", file=sys.stderr)

    return articles


# ── Pre-filter: keep N most recent per company ────────────────────────────────

def prefilter_articles(all_articles: list[dict]) -> list[dict]:
    """Keep MAX_ARTICLES_PER_COMPANY most recent articles per ticker."""
    by_ticker: dict[str, list] = {}
    for a in all_articles:
        by_ticker.setdefault(a["ticker"], []).append(a)
    filtered = []
    for ticker, articles in by_ticker.items():
        sorted_arts = sorted(
            articles, key=lambda x: x.get("published_at", ""), reverse=True
        )
        filtered.extend(sorted_arts[:MAX_ARTICLES_PER_COMPANY])
    print(f"Pre-filtered to {len(filtered)} articles ({MAX_ARTICLES_PER_COMPANY} max/company).")
    return filtered


# ── Fetch social signals ──────────────────────────────────────────────────────

def fetch_reddit_posts(dry_run: bool = False) -> list[dict]:
    """Fetch today's top posts from market-relevant subreddits (no auth required)."""
    if dry_run:
        print("[DRY-RUN] Skipping Reddit fetch.")
        return []

    posts: list[dict] = []
    headers = {"User-Agent": "CarmenBriefingBot/1.0"}

    for sub_name in MARKET_REDDIT_SUBS:
        try:
            url  = f"https://www.reddit.com/r/{sub_name}/top.json?t=day&limit=100"
            resp = requests.get(url, headers=headers, timeout=15)
            resp.raise_for_status()
            for child in resp.json().get("data", {}).get("children", []):
                post = child.get("data", {})
                posts.append({
                    "title": (post.get("title") or "").lower(),
                    "score": max(0, post.get("score") or 0),
                })
            time.sleep(1)   # be polite to Reddit's servers
        except Exception as e:
            print(f"  WARN: Reddit r/{sub_name}: {e}", file=sys.stderr)

    print(f"Fetched {len(posts)} Reddit posts from {len(MARKET_REDDIT_SUBS)} subreddits.")
    return posts


def fetch_hn_posts(dry_run: bool = False) -> list[dict]:
    """Fetch today's HN stories via Algolia API (no key required)."""
    if dry_run:
        print("[DRY-RUN] Skipping HN fetch.")
        return []

    cutoff_ts = int((datetime.now(timezone.utc) - timedelta(hours=24)).timestamp())
    url = (
        "https://hn.algolia.com/api/v1/search_by_date"
        f"?tags=story&numericFilters=created_at_i>{cutoff_ts}&hitsPerPage=200"
    )
    try:
        resp = requests.get(url, timeout=20)
        resp.raise_for_status()
        hits = resp.json().get("hits", [])
        posts = [
            {
                "title": (h.get("title") or "").lower(),
                "score": max(0, h.get("points") or 0),
            }
            for h in hits
            if h.get("title")
        ]
        print(f"Fetched {len(posts)} HN stories.")
        return posts
    except Exception as e:
        print(f"  WARN: HN fetch failed: {e}", file=sys.stderr)
        return []


# ── TF-IDF story clustering ───────────────────────────────────────────────────

def build_clusters(articles: list[dict]) -> list[int]:
    """
    Assign cluster IDs by TF-IDF cosine similarity >= SIM_THRESHOLD.
    Returns a list of cluster IDs, one per article.
    """
    if len(articles) < 2:
        return list(range(len(articles)))

    texts = [a["headline"] + " " + a.get("summary_snippet", "") for a in articles]

    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.metrics.pairwise import cosine_similarity

        vec        = TfidfVectorizer(stop_words="english", max_features=5000)
        tfidf      = vec.fit_transform(texts)
        sim_matrix = cosine_similarity(tfidf)

        cluster_ids  = [-1] * len(articles)
        next_cluster = 0

        for i in range(len(articles)):
            if cluster_ids[i] != -1:
                continue
            cluster_ids[i] = next_cluster
            for j in range(i + 1, len(articles)):
                if cluster_ids[j] == -1 and sim_matrix[i, j] >= SIM_THRESHOLD:
                    cluster_ids[j] = next_cluster
            next_cluster += 1

        return cluster_ids

    except ImportError:
        print("  WARN: scikit-learn not installed — each article is its own cluster.",
              file=sys.stderr)
        return list(range(len(articles)))


def _cluster_sizes(cluster_ids: list[int]) -> dict[int, int]:
    sizes: dict[int, int] = {}
    for cid in cluster_ids:
        sizes[cid] = sizes.get(cid, 0) + 1
    return sizes


# ── Scoring helpers ───────────────────────────────────────────────────────────

_STOP = {
    "the", "a", "an", "in", "on", "at", "to", "for", "of", "and", "or",
    "is", "are", "was", "were", "has", "have", "will", "with", "by",
    "from", "as", "its", "it", "that", "this", "be", "but", "not",
}

def _social_score_company(
    headline:      str,
    company_name:  str,
    ticker:        str,
    reddit_posts:  list[dict],
    hn_posts:      list[dict],
) -> float:
    """
    Normalized 0–1 social score for a company article.
    A post matches if it mentions the ticker or company name
    AND has ≥ 2 words in common with the headline.
    """
    ticker_lower  = ticker.lower()
    company_lower = company_name.lower()
    words         = set(headline.lower().split()) - _STOP

    def _matches(post_title: str) -> bool:
        if ticker_lower not in post_title and company_lower not in post_title:
            return False
        post_words = set(post_title.split()) - _STOP
        return len(words & post_words) >= 2 or ticker_lower in post_title

    best_reddit = max(
        (p["score"] for p in reddit_posts if _matches(p["title"])), default=0
    )
    best_hn = max(
        (p["score"] for p in hn_posts if _matches(p["title"])), default=0
    )

    r_norm = min(math.log1p(best_reddit) / math.log1p(5000), 1.0) if best_reddit > 0 else 0.0
    h_norm = min(math.log1p(best_hn)     / math.log1p(500),  1.0) if best_hn     > 0 else 0.0

    if best_reddit > 0 and best_hn > 0:
        return (r_norm + h_norm) / 2
    elif best_reddit > 0:
        return r_norm
    elif best_hn > 0:
        return h_norm
    else:
        return SOCIAL_NOT_FOUND


def _recency_score(published_at: str) -> float:
    """Exponential decay with 12-hour half-life."""
    if not published_at:
        return 0.50
    try:
        pub = datetime.fromisoformat(published_at)
        if pub.tzinfo is None:
            pub = pub.replace(tzinfo=timezone.utc)
        age_hours = (datetime.now(timezone.utc) - pub).total_seconds() / 3600
        return math.exp(-age_hours * math.log(2) / 12)
    except Exception:
        return 0.50


# ── Score all articles ────────────────────────────────────────────────────────

def score_popularity(
    articles:     list[dict],
    reddit_posts: list[dict],
    hn_posts:     list[dict],
    cluster_ids:  list[int],
    sizes:        dict[int, int],
) -> list[dict]:
    """Apply composite popularity formula to each article."""
    for i, a in enumerate(articles):
        social    = _social_score_company(
            a["headline"], a["company"], a["ticker"], reddit_posts, hn_posts
        )
        authority = get_authority(a["source_url"])
        coverage  = min(sizes.get(cluster_ids[i], 1) / 5.0, 1.0)
        recency   = _recency_score(a["published_at"])

        composite = (
            W_SOCIAL    * social    +
            W_AUTHORITY * authority +
            W_COVERAGE  * coverage  +
            W_TREND     * TREND_SCORE +
            W_RECENCY   * recency
        )
        composite = min(composite, 1.0)

        a["score"] = max(1, round(composite * 9) + 1)
        a["popularity"] = {
            "social":    round(social,    3),
            "authority": round(authority, 3),
            "coverage":  round(coverage,  3),
            "trend":     TREND_SCORE,
            "recency":   round(recency,   3),
            "composite": round(composite, 3),
        }

    return articles


# ── Per-company best story selection ─────────────────────────────────────────

def select_best_per_company(all_articles: list[dict]) -> list[dict]:
    """Keep only the highest-scoring article per company."""
    by_ticker: dict[str, list] = {}
    for a in all_articles:
        by_ticker.setdefault(a["ticker"], []).append(a)
    best = []
    for ticker, articles in by_ticker.items():
        top = max(articles, key=lambda x: x["score"])
        best.append(top)
    return best


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="Skip Reddit/HN API calls; use baseline social scores.")
    args = parser.parse_args()

    TMP_DIR.mkdir(exist_ok=True)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=CUTOFF_HOURS)

    companies    = get_all_companies()
    all_articles = []

    print(f"Fetching news for {len(companies)} companies…")
    for company in companies:
        articles = fetch_company_news(company, cutoff)
        all_articles.extend(articles)
        if articles:
            print(f"  {company['ticker']}: {len(articles)} articles")

    print(f"Total: {len(all_articles)} company articles.")
    all_articles = prefilter_articles(all_articles)

    # Social signals
    reddit_posts = fetch_reddit_posts(args.dry_run)
    hn_posts     = fetch_hn_posts(args.dry_run)

    # Cluster and score
    print(f"Clustering {len(all_articles)} articles…")
    cluster_ids = build_clusters(all_articles)
    sizes       = _cluster_sizes(cluster_ids)
    print(f"  {len(set(cluster_ids))} story clusters identified.")

    all_articles = score_popularity(all_articles, reddit_posts, hn_posts, cluster_ids, sizes)
    best         = select_best_per_company(all_articles)

    OUT_FILE.write_text(json.dumps(best, indent=2, ensure_ascii=False))
    print(f"Saved {len(best)} company stories → {OUT_FILE}")

    if args.dry_run:
        print("\n[DRY-RUN] Best company stories (popularity-ranked):")
        for s in sorted(best, key=lambda x: -x["score"])[:10]:
            pop = s.get("popularity", {})
            print(
                f"  [T{s['tier']}] {s['ticker']} score={s['score']} "
                f"composite={pop.get('composite','?')} | {s['headline'][:70]}"
            )


if __name__ == "__main__":
    main()
