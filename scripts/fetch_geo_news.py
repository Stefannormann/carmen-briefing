"""
Fetch, filter, score, and select geopolitical news stories.

Two-gate selection system:
  Gate 1 – keyword relevance: at least one geo keyword in headline + summary
  Gate 2 – composite popularity score:
            0.35 * social    (Reddit upvotes + HN points, normalised)
          + 0.15 * authority (publisher domain reputation)
          + 0.25 * coverage  (TF-IDF cluster size: how many sources cover it)
          + 0.15 * trend     (flat 0.50 — pytrends dropped)
          + 0.10 * recency   (exponential decay, 12-hour half-life)

Saves selected stories to tmp/geo_stories.json.

Usage:
    python scripts/fetch_geo_news.py [--dry-run]
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
from config.geo_sources import GEO_RSS_TIER_1, GEO_RSS_TIER_2
from config.geo_keywords import GEO_KEYWORDS
from config.publisher_authority import get_authority
from scripts.watchlist import get_all_names

# ── Reddit subreddits for geo news ────────────────────────────────────────────
GEO_REDDIT_SUBS = [
    "worldnews", "geopolitics", "economics",
    "technology", "europe", "China", "taiwan",
]

# ── Config ────────────────────────────────────────────────────────────────────
TMP_DIR = Path("tmp")
OUT_FILE = TMP_DIR / "geo_stories.json"

CUTOFF_HOURS       = 24
MAX_GEO_STORIES    = 3
SIM_THRESHOLD      = 0.65   # TF-IDF cosine similarity for story clustering

# Composite score weights (must sum to 1.0)
W_SOCIAL    = 0.35
W_AUTHORITY = 0.15
W_COVERAGE  = 0.25
W_TREND     = 0.15
W_RECENCY   = 0.10
TREND_SCORE = 0.50   # constant (pytrends dropped)

# Social score assigned when no Reddit/HN match is found
SOCIAL_NOT_FOUND = 0.20


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
            summary  = getattr(entry, "summary", "")[:500].strip()
            link     = getattr(entry, "link", "")
            if not headline:
                continue
            articles.append({
                "headline":        headline,
                "summary_snippet": summary,
                "source_url":      link,
                "feed_url":        url,
                "feed_tier":       feed_tier,
                "published_at":    published.isoformat() if published else "",
                "topic":           [],
                "score":           5,
                "watchlist_flag":  False,
                "watchlist_note":  "",
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
    if len(wa) < n:
        return False
    seq_a = [" ".join(wa[i:i+n]) for i in range(len(wa) - n + 1)]
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


# ── Step 3: Gate 1 — keyword relevance filter ─────────────────────────────────

def gate1_filter(articles: list[dict]) -> list[dict]:
    """Keep only articles with at least one geo keyword in headline or summary."""
    all_keywords = [kw for kws in GEO_KEYWORDS.values() for kw in kws]
    passed = []
    for a in articles:
        text = (a["headline"] + " " + a["summary_snippet"]).lower()
        if any(kw in text for kw in all_keywords):
            passed.append(a)
    print(f"Gate 1 (keyword): {len(passed)}/{len(articles)} articles passed.")
    return passed


# ── Step 4: Topic tagging (metadata only) ────────────────────────────────────

def tag_topics(articles: list[dict]) -> list[dict]:
    for a in articles:
        text = (a["headline"] + " " + a["summary_snippet"]).lower()
        matched = [t for t, kws in GEO_KEYWORDS.items() if any(kw in text for kw in kws)]
        a["topic"] = matched if matched else ["other"]
    return articles


# ── Step 5a: Fetch Reddit posts ───────────────────────────────────────────────

def fetch_reddit_posts(dry_run: bool = False) -> list[dict]:
    """Fetch today's top posts from geo-relevant subreddits."""
    if dry_run:
        print("[DRY-RUN] Skipping Reddit fetch.")
        return []

    client_id     = os.environ.get("REDDIT_CLIENT_ID", "")
    client_secret = os.environ.get("REDDIT_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        print("  WARN: REDDIT_CLIENT_ID/SECRET not set — social signal will use baseline.",
              file=sys.stderr)
        return []

    try:
        import praw
    except ImportError:
        print("  WARN: praw not installed — social signal will use baseline.", file=sys.stderr)
        return []

    posts: list[dict] = []
    try:
        reddit = praw.Reddit(
            client_id=client_id,
            client_secret=client_secret,
            user_agent="CarmenBriefingBot/1.0 (read-only news aggregator)",
        )
        for sub_name in GEO_REDDIT_SUBS:
            try:
                sub = reddit.subreddit(sub_name)
                for post in sub.top(time_filter="day", limit=75):
                    posts.append({
                        "title": post.title.lower(),
                        "score": max(0, post.score),
                    })
            except Exception as e:
                print(f"  WARN: Reddit r/{sub_name}: {e}", file=sys.stderr)
    except Exception as e:
        print(f"  WARN: Reddit init failed: {e}", file=sys.stderr)

    print(f"Fetched {len(posts)} Reddit posts from {len(GEO_REDDIT_SUBS)} subreddits.")
    return posts


# ── Step 5b: Fetch Hacker News posts ─────────────────────────────────────────

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


# ── Step 6: TF-IDF story clustering ──────────────────────────────────────────

def build_clusters(articles: list[dict]) -> list[int]:
    """
    Assign a cluster ID to each article based on TF-IDF cosine similarity.
    Articles with similarity >= SIM_THRESHOLD share a cluster.
    Returns a list of cluster IDs (one per article).
    """
    if len(articles) < 2:
        return list(range(len(articles)))

    texts = [a["headline"] + " " + a.get("summary_snippet", "") for a in articles]

    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.metrics.pairwise import cosine_similarity

        vectorizer = TfidfVectorizer(stop_words="english", max_features=5000)
        tfidf      = vectorizer.fit_transform(texts)
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


# ── Step 7: Scoring helpers ───────────────────────────────────────────────────

_STOP = {
    "the", "a", "an", "in", "on", "at", "to", "for", "of", "and", "or",
    "is", "are", "was", "were", "has", "have", "will", "with", "by",
    "from", "as", "its", "it", "that", "this", "be", "but", "not",
}

def _social_score(headline: str, reddit_posts: list[dict], hn_posts: list[dict]) -> float:
    """Normalized 0–1 social score based on best-matching Reddit/HN post."""
    words = set(headline.lower().split()) - _STOP
    if not words:
        return SOCIAL_NOT_FOUND

    def _overlap(post_title: str) -> float:
        post_words = set(post_title.split()) - _STOP
        if not post_words:
            return 0.0
        shared = len(words & post_words)
        return shared / min(len(words), len(post_words), 8)

    MATCH_THRESHOLD = 0.35

    best_reddit = max(
        (p["score"] for p in reddit_posts if _overlap(p["title"]) >= MATCH_THRESHOLD),
        default=0,
    )
    best_hn = max(
        (p["score"] for p in hn_posts if _overlap(p["title"]) >= MATCH_THRESHOLD),
        default=0,
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
    """Exponential decay with 12-hour half-life: 0h→1.0, 12h→0.50, 24h→0.25."""
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


def _headline_multiplier(headline: str) -> float:
    """1.5× boost when geo keywords appear in the headline itself (not just summary)."""
    headline_lower = headline.lower()
    for kws in GEO_KEYWORDS.values():
        if any(kw in headline_lower for kw in kws):
            return 1.5
    return 1.0


# ── Step 8: Compute composite popularity scores ───────────────────────────────

def score_popularity(
    articles:      list[dict],
    reddit_posts:  list[dict],
    hn_posts:      list[dict],
    cluster_ids:   list[int],
    sizes:         dict[int, int],
) -> list[dict]:
    """Apply composite popularity formula to each article."""
    for i, a in enumerate(articles):
        social    = _social_score(a["headline"], reddit_posts, hn_posts)
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
        # Headline keyword multiplier capped at 1.0
        composite = min(composite * _headline_multiplier(a["headline"]), 1.0)

        # Store as 1–10 integer for generate_script.py / prioritise_stories() compatibility
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


# ── Step 9: Watchlist tagging ─────────────────────────────────────────────────

def tag_watchlist(articles: list[dict]) -> list[dict]:
    """Flag articles that mention a watchlist company by name."""
    company_names = get_all_names()
    for a in articles:
        text = (a["headline"] + " " + a["summary_snippet"]).lower()
        for name in company_names:
            if name.lower() in text:
                a["watchlist_flag"] = True
                a["watchlist_note"] = (
                    f"{name} may be directly affected by this development."
                )
                break
    return articles


# ── Step 10: Story selection ──────────────────────────────────────────────────

def select_stories(articles: list[dict]) -> list[dict]:
    """Select top MAX_GEO_STORIES with topic diversity, highest popularity first."""
    sorted_articles = sorted(articles, key=lambda x: -x["score"])
    selected: list[dict] = []
    covered_topics: set[str] = set()

    def pick(candidates: list[dict], min_score: int = 0):
        for a in candidates:
            if len(selected) >= MAX_GEO_STORIES:
                break
            if a["score"] < min_score:
                continue
            topics  = set(a["topic"])
            overlap = topics & covered_topics
            # Allow same-topic duplicate only if both articles score ≥ 8
            if overlap and a["score"] < 8:
                continue
            selected.append(a)
            covered_topics.update(topics)

    # Pass 1: quality threshold
    pick(sorted_articles, min_score=4)
    # Pass 2: fill any remaining slots
    pick(sorted_articles, min_score=1)
    # Pass 3: fallback — take top N regardless of score
    if not selected:
        print("  WARN: No stories passed score threshold — using top articles as fallback.")
        pick(sorted_articles, min_score=0)

    print(f"Selected {len(selected)} geopolitical stories.")
    return selected


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Skip Reddit/HN API calls; use baseline social scores instead.",
    )
    args = parser.parse_args()

    TMP_DIR.mkdir(exist_ok=True)

    # ── Fetch & Gate 1 ────────────────────────────────────────────────────────
    articles = fetch_feeds(args.dry_run)
    articles = deduplicate(articles)
    articles = gate1_filter(articles)
    articles = tag_topics(articles)

    if not articles:
        print("WARNING: No articles passed Gate 1 — saving empty output.", file=sys.stderr)
        OUT_FILE.write_text(json.dumps([], indent=2))
        return

    # ── Social signals ─────────────────────────────────────────────────────────
    reddit_posts = fetch_reddit_posts(args.dry_run)
    hn_posts     = fetch_hn_posts(args.dry_run)

    # ── Gate 2: popularity scoring ────────────────────────────────────────────
    print(f"Clustering {len(articles)} articles…")
    cluster_ids = build_clusters(articles)
    sizes       = _cluster_sizes(cluster_ids)
    print(f"  {len(set(cluster_ids))} story clusters identified.")

    articles = score_popularity(articles, reddit_posts, hn_posts, cluster_ids, sizes)
    articles = tag_watchlist(articles)
    selected = select_stories(articles)

    OUT_FILE.write_text(json.dumps(selected, indent=2, ensure_ascii=False))
    print(f"Saved {len(selected)} stories → {OUT_FILE}")

    if args.dry_run:
        print("\n[DRY-RUN] Selected stories:")
        for s in selected:
            pop = s.get("popularity", {})
            print(
                f"  [T{s['feed_tier']}] score={s['score']} "
                f"(soc={pop.get('social','?')} auth={pop.get('authority','?')} "
                f"cov={pop.get('coverage','?')} rec={pop.get('recency','?')}) "
                f"| {s['headline'][:80]}"
            )


if __name__ == "__main__":
    main()
