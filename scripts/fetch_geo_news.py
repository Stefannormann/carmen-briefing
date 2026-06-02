"""
Fetch, filter, score, and select stories for one content segment.

Two-gate selection system:
  Gate 1 – keyword relevance: at least one segment keyword in headline + summary
  Gate 2 – composite popularity score:
            0.35 * social    (Reddit upvotes + HN points, normalised)
          + 0.15 * authority (publisher domain reputation)
          + 0.25 * coverage  (TF-IDF cluster size: how many sources cover it)
          + 0.15 * trend     (flat 0.50 — pytrends dropped)
          + 0.10 * recency   (exponential decay, 12-hour half-life)

Usage:
    python scripts/fetch_geo_news.py --segment strategic   # → tmp/strategic_stories.json
    python scripts/fetch_geo_news.py --segment tech        # → tmp/tech_stories.json
    python scripts/fetch_geo_news.py                       # defaults to strategic
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
from config.geo_keywords import STRATEGIC_KEYWORDS, TECH_KEYWORDS
from config.publisher_authority import get_authority
from scripts.watchlist import get_all_names

# ── Reddit subreddits per segment ─────────────────────────────────────────────
STRATEGIC_REDDIT_SUBS = [
    "worldnews", "geopolitics", "economics", "europe", "China", "taiwan",
]
TECH_REDDIT_SUBS = [
    "technology", "MachineLearning", "artificial", "hardware",
    "netsec", "Futurology", "singularity",
]

# ── Config ────────────────────────────────────────────────────────────────────
TMP_DIR = Path("tmp")

CUTOFF_HOURS    = 24
MAX_STORIES     = 3
SIM_THRESHOLD   = 0.65

W_SOCIAL    = 0.35
W_AUTHORITY = 0.15
W_COVERAGE  = 0.25
W_TREND     = 0.15
W_RECENCY   = 0.10
TREND_SCORE = 0.50
SOCIAL_NOT_FOUND = 0.20

# ── filters.json runtime overrides ───────────────────────────────────────────
_FILTERS_CANDIDATES = [Path("filters.json"), Path("/opt/carmen/filters.json")]

def _load_filters() -> dict | None:
    for p in _FILTERS_CANDIDATES:
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                pass
    return None

def _get_sources() -> tuple[list[str], list[str]]:
    f = _load_filters()
    if f and "geo_sources" in f:
        s = f["geo_sources"]
        return s.get("tier1", GEO_RSS_TIER_1), s.get("tier2", GEO_RSS_TIER_2)
    return GEO_RSS_TIER_1, GEO_RSS_TIER_2

def _get_keywords(segment: str) -> dict:
    f = _load_filters()
    key = "strategic_keywords" if segment == "strategic" else "tech_keywords"
    if f and key in f:
        return f[key]
    return STRATEGIC_KEYWORDS if segment == "strategic" else TECH_KEYWORDS


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

    tier1_feeds, tier2_feeds = _get_sources()
    print("Fetching Tier 1 RSS feeds…")
    for url in tier1_feeds:
        parse_feed(url, 1)
    print("Fetching Tier 2 RSS feeds…")
    for url in tier2_feeds:
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
        duplicate = any(
            _shared_consecutive(article["headline"], e["headline"]) for e in kept
        )
        if not duplicate:
            kept.append(article)
    print(f"After deduplication: {len(kept)} articles.")
    return kept


# ── Step 3: Gate 1 — keyword relevance filter ─────────────────────────────────

def gate1_filter(articles: list[dict], segment: str) -> list[dict]:
    keywords = _get_keywords(segment)
    all_kws  = [kw for kws in keywords.values() for kw in kws]
    passed = [
        a for a in articles
        if any(kw in (a["headline"] + " " + a["summary_snippet"]).lower() for kw in all_kws)
    ]
    print(f"Gate 1 ({segment} keywords): {len(passed)}/{len(articles)} articles passed.")
    return passed


# ── Step 4: Topic tagging ────────────────────────────────────────────────────

def tag_topics(articles: list[dict], segment: str) -> list[dict]:
    keywords = _get_keywords(segment)
    for a in articles:
        text = (a["headline"] + " " + a["summary_snippet"]).lower()
        matched = [t for t, kws in keywords.items() if any(kw in text for kw in kws)]
        a["topic"] = matched if matched else ["other"]
    return articles


# ── Step 5a: Fetch Reddit ─────────────────────────────────────────────────────

def fetch_reddit_posts(segment: str, dry_run: bool = False) -> list[dict]:
    if dry_run:
        print("[DRY-RUN] Skipping Reddit fetch.")
        return []

    subs   = STRATEGIC_REDDIT_SUBS if segment == "strategic" else TECH_REDDIT_SUBS
    posts: list[dict] = []
    headers = {"User-Agent": "CarmenBriefingBot/1.0"}

    for sub_name in subs:
        try:
            url  = f"https://www.reddit.com/r/{sub_name}/top.json?t=day&limit=75"
            resp = requests.get(url, headers=headers, timeout=15)
            resp.raise_for_status()
            for child in resp.json().get("data", {}).get("children", []):
                post = child.get("data", {})
                posts.append({
                    "title": (post.get("title") or "").lower(),
                    "score": max(0, post.get("score") or 0),
                })
            time.sleep(1)
        except Exception as e:
            print(f"  WARN: Reddit r/{sub_name}: {e}", file=sys.stderr)

    print(f"Fetched {len(posts)} Reddit posts from {len(subs)} subreddits.")
    return posts


# ── Step 5b: Fetch HN ─────────────────────────────────────────────────────────

def fetch_hn_posts(dry_run: bool = False) -> list[dict]:
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
            {"title": (h.get("title") or "").lower(), "score": max(0, h.get("points") or 0)}
            for h in hits if h.get("title")
        ]
        print(f"Fetched {len(posts)} HN stories.")
        return posts
    except Exception as e:
        print(f"  WARN: HN fetch failed: {e}", file=sys.stderr)
        return []


# ── Step 6: TF-IDF clustering ─────────────────────────────────────────────────

def build_clusters(articles: list[dict]) -> list[int]:
    if len(articles) < 2:
        return list(range(len(articles)))
    texts = [a["headline"] + " " + a.get("summary_snippet", "") for a in articles]
    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.metrics.pairwise import cosine_similarity
        vectorizer  = TfidfVectorizer(stop_words="english", max_features=5000)
        tfidf       = vectorizer.fit_transform(texts)
        sim_matrix  = cosine_similarity(tfidf)
        cluster_ids = [-1] * len(articles)
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
        print("  WARN: scikit-learn not installed — each article is its own cluster.", file=sys.stderr)
        return list(range(len(articles)))

def _cluster_sizes(cluster_ids: list[int]) -> dict[int, int]:
    sizes: dict[int, int] = {}
    for cid in cluster_ids:
        sizes[cid] = sizes.get(cid, 0) + 1
    return sizes


# ── Step 7: Scoring helpers ───────────────────────────────────────────────────

_STOP = {
    "the","a","an","in","on","at","to","for","of","and","or",
    "is","are","was","were","has","have","will","with","by",
    "from","as","its","it","that","this","be","but","not",
}

def _social_score(headline: str, reddit_posts: list[dict], hn_posts: list[dict]) -> float:
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
    best_reddit = max((p["score"] for p in reddit_posts if _overlap(p["title"]) >= MATCH_THRESHOLD), default=0)
    best_hn     = max((p["score"] for p in hn_posts     if _overlap(p["title"]) >= MATCH_THRESHOLD), default=0)

    r_norm = min(math.log1p(best_reddit) / math.log1p(5000), 1.0) if best_reddit > 0 else 0.0
    h_norm = min(math.log1p(best_hn)     / math.log1p(500),  1.0) if best_hn     > 0 else 0.0

    if best_reddit > 0 and best_hn > 0:
        return (r_norm + h_norm) / 2
    elif best_reddit > 0:
        return r_norm
    elif best_hn > 0:
        return h_norm
    return SOCIAL_NOT_FOUND


def _recency_score(published_at: str) -> float:
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


def _headline_multiplier(headline: str, segment: str) -> float:
    headline_lower = headline.lower()
    for kws in _get_keywords(segment).values():
        if any(kw in headline_lower for kw in kws):
            return 1.5
    return 1.0


# ── Step 8: Composite scoring ─────────────────────────────────────────────────

def score_popularity(
    articles:     list[dict],
    reddit_posts: list[dict],
    hn_posts:     list[dict],
    cluster_ids:  list[int],
    sizes:        dict[int, int],
    segment:      str,
) -> list[dict]:
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
        composite = min(composite * _headline_multiplier(a["headline"], segment), 1.0)
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
    company_names = get_all_names()
    for a in articles:
        text = (a["headline"] + " " + a["summary_snippet"]).lower()
        for name in company_names:
            if name.lower() in text:
                a["watchlist_flag"] = True
                a["watchlist_note"] = f"{name} may be directly affected by this development."
                break
    return articles


# ── Step 10: Story selection ──────────────────────────────────────────────────

def select_stories(articles: list[dict]) -> list[dict]:
    sorted_articles = sorted(articles, key=lambda x: -x["score"])
    selected: list[dict] = []
    covered_topics: set[str] = set()

    def pick(candidates: list[dict], min_score: int = 0):
        for a in candidates:
            if len(selected) >= MAX_STORIES:
                break
            if a["score"] < min_score:
                continue
            topics  = set(a["topic"])
            overlap = topics & covered_topics
            if overlap and a["score"] < 8:
                continue
            selected.append(a)
            covered_topics.update(topics)

    pick(sorted_articles, min_score=4)
    pick(sorted_articles, min_score=1)
    if not selected:
        print("  WARN: No stories passed score threshold — using top articles as fallback.")
        pick(sorted_articles, min_score=0)

    print(f"Selected {len(selected)} stories.")
    return selected


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--segment",
        choices=["strategic", "tech"],
        default="strategic",
        help="Which content segment to fetch (default: strategic)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Skip Reddit/HN API calls; use baseline social scores.",
    )
    args = parser.parse_args()

    segment  = args.segment
    out_file = TMP_DIR / f"{segment}_stories.json"
    label    = "Global Strategic Affairs" if segment == "strategic" else "AI & Tech"

    print(f"\n=== Fetching: {label} ===")
    TMP_DIR.mkdir(exist_ok=True)

    articles = fetch_feeds(args.dry_run)
    articles = deduplicate(articles)
    articles = gate1_filter(articles, segment)
    articles = tag_topics(articles, segment)

    if not articles:
        print(f"WARNING: No articles passed Gate 1 for {label} — saving empty output.", file=sys.stderr)
        out_file.write_text(json.dumps([], indent=2))
        # Also write backward-compat geo_stories.json for strategic segment
        if segment == "strategic":
            (TMP_DIR / "geo_stories.json").write_text(json.dumps([], indent=2))
        return

    reddit_posts = fetch_reddit_posts(segment, args.dry_run)
    hn_posts     = fetch_hn_posts(args.dry_run)

    print(f"Clustering {len(articles)} articles…")
    cluster_ids = build_clusters(articles)
    sizes       = _cluster_sizes(cluster_ids)
    print(f"  {len(set(cluster_ids))} story clusters identified.")

    articles = score_popularity(articles, reddit_posts, hn_posts, cluster_ids, sizes, segment)
    articles = tag_watchlist(articles)
    selected = select_stories(articles)

    out_file.write_text(json.dumps(selected, indent=2, ensure_ascii=False))
    print(f"Saved {len(selected)} {label} stories → {out_file}")

    # Backward-compat alias for strategic segment
    if segment == "strategic":
        (TMP_DIR / "geo_stories.json").write_text(json.dumps(selected, indent=2, ensure_ascii=False))

    if args.dry_run:
        print(f"\n[DRY-RUN] {label} stories:")
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
