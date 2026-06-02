"""
Keyword sets for Gate 1 filtering and topic tagging.

STRATEGIC_KEYWORDS  — Global Strategic Affairs segment
TECH_KEYWORDS       — AI & Tech segment
GEO_KEYWORDS        — backward-compatibility alias for STRATEGIC_KEYWORDS
"""

STRATEGIC_KEYWORDS = {
    "us_china": [
        "us-china", "us china", "china relations", "beijing", "xi jinping",
        "taiwan", "taiwan strait", "south china sea", "belt and road",
        "bri", "sino-us", "chinese",
    ],
    "us_europe": [
        "us-europe", "us europe", "transatlantic", "nato",
        "trump europe", "biden europe", "us-nato",
    ],
    "eu_geopolitics": [
        "european union", "eu-china", "eu china", "von der leyen",
        "brussels", "european commission", "europe china",
    ],
    "global_trade": [
        "tariffs", "sanctions", "export controls", "trade restrictions",
        "trade war", "global trade", "wto", "import duties",
        "economic coercion", "trade policy", "export bans",
        "sanctions evasion",
    ],
    "geoeconomics": [
        "geoeconomics", "strategic competition", "great power rivalry",
        "geopolitics", "geopolitical", "geostrategic", "industrial policy",
        "national security", "foreign policy", "diplomatic tensions",
        "global alliances", "international relations", "global power balance",
        "economic nationalism", "sovereign wealth", "global investment",
        "economic resilience", "geopolitical risk",
    ],
    "resources": [
        "rare earth", "critical minerals", "strategic resources",
        "lithium", "cobalt", "gallium", "germanium", "resource security",
        "reshoring", "nearshoring", "friendshoring", "deglobalization",
        "manufacturing capacity",
    ],
    "energy": [
        "energy security", "energy transition", "oil markets",
        "natural gas", "lng", "commodity markets", "energy crisis",
        "oil price", "fossil fuel", "pipeline", "opec",
    ],
    "supply_chain": [
        "supply chain", "supply chain disruption", "logistics bottlenecks",
        "shipping routes", "maritime security", "supply chain resilience",
    ],
    "macro": [
        "macroeconomics", "inflation", "interest rates", "central banks",
        "monetary policy", "fiscal policy", "recession risk",
        "economic slowdown", "financial stability", "sovereign debt",
        "currency markets", "emerging markets", "global economic order",
    ],
    "conflicts": [
        "ukraine war", "ukraine", "middle east conflict", "regional conflicts",
        "military buildup", "defense spending", "strategic deterrence",
        "indo-pacific", "brics", "food security",
    ],
    "climate_risk": [
        "climate risks", "natural disasters", "earthquakes", "droughts",
        "floods", "extreme weather", "environmental disruption",
        "demographic decline", "labor shortages", "migration pressure",
    ],
}

TECH_KEYWORDS = {
    "ai_core": [
        "artificial intelligence", "ai development", "agi",
        "machine learning", "large language model", "llm",
        "generative ai", "ai race", "foundation model",
        "ai model", "ai system", "deep learning", "neural network",
    ],
    "semiconductors": [
        "semiconductor", "semiconductor industry", "semiconductor supply chain",
        "chip manufacturing", "semiconductor equipment", "advanced chips",
        "chip", "nvidia", "tsmc", "intel fab", "chip act",
        "chips act", "advanced manufacturing",
    ],
    "advanced_tech": [
        "quantum computing", "biotechnology", "space technology",
        "automation", "robotics", "advanced computing",
        "autonomous systems", "synthetic biology",
    ],
    "cyber": [
        "cyber security", "cybersecurity", "cyber warfare",
        "information warfare", "cyber attack", "ransomware",
        "data breach", "hacking", "digital warfare",
    ],
    "digital_policy": [
        "ai regulation", "technology transfer", "technological sovereignty",
        "digital sovereignty", "critical technologies", "strategic industries",
        "tech policy", "ai governance", "ai safety",
    ],
    "infrastructure": [
        "undersea cables", "satellite networks", "critical infrastructure",
        "battery technology", "energy storage", "grid technology",
        "data center", "cloud infrastructure",
    ],
}

# Backward-compatibility alias — existing code that imports GEO_KEYWORDS still works
GEO_KEYWORDS = STRATEGIC_KEYWORDS
