"""
Publisher authority scores for news sources.

Scale: 0.0 (low / unknown) – 1.0 (highest tier wire service).
Domains not listed default to DEFAULT_AUTHORITY (0.50).

These scores feed the authority signal in the composite popularity formula:
  popularity = 0.35*social + 0.15*authority + 0.25*coverage + 0.15*trend + 0.10*recency
"""

from urllib.parse import urlparse

PUBLISHER_AUTHORITY: dict[str, float] = {
    # ── Tier A: wire services & top-tier international papers ────────────────
    "reuters.com":          1.00,
    "apnews.com":           1.00,
    "bbc.com":              0.95,
    "bbc.co.uk":            0.95,
    "bloomberg.com":        0.95,
    "ft.com":               0.93,
    "wsj.com":              0.93,
    "economist.com":        0.93,
    "nytimes.com":          0.90,
    "washingtonpost.com":   0.88,
    "theguardian.com":      0.87,

    # ── Tier B: foreign policy / geopolitics specialists ─────────────────────
    "foreignpolicy.com":    0.90,
    "foreignaffairs.com":   0.92,
    "scmp.com":             0.83,
    "politico.com":         0.85,
    "politico.eu":          0.82,
    "euractiv.com":         0.80,
    "aljazeera.com":        0.76,
    "dw.com":               0.80,
    "axios.com":            0.80,
    "nikkei.com":           0.80,
    "lemonde.fr":           0.83,
    "spiegel.de":           0.82,

    # ── Tier C: tech & science ────────────────────────────────────────────────
    "technologyreview.com": 0.88,
    "wired.com":            0.80,
    "theverge.com":         0.76,
    "techcrunch.com":       0.73,
    "arstechnica.com":      0.75,

    # ── Tier D: financial / markets ───────────────────────────────────────────
    "cnbc.com":             0.76,
    "marketwatch.com":      0.70,
    "finance.yahoo.com":    0.62,
    "nasdaq.com":           0.68,
    "seekingalpha.com":     0.52,
    "investing.com":        0.60,

    # ── Regional ──────────────────────────────────────────────────────────────
    "cphpost.dk":           0.52,

    # ── Lower authority / aggregators ────────────────────────────────────────
    "businessinsider.com":  0.58,
    "msn.com":              0.40,
    "yahoo.com":            0.40,
    "huffpost.com":         0.42,
}

DEFAULT_AUTHORITY = 0.50


def get_authority(url: str) -> float:
    """Return the authority score for a URL's domain. Strips www. prefix."""
    if not url:
        return DEFAULT_AUTHORITY
    try:
        domain = urlparse(url).netloc.lower()
        if domain.startswith("www."):
            domain = domain[4:]
        return PUBLISHER_AUTHORITY.get(domain, DEFAULT_AUTHORITY)
    except Exception:
        return DEFAULT_AUTHORITY
