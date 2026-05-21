"""Keyword sets for pre-scoring topic tagging of geopolitical articles."""

GEO_KEYWORDS = {
    "usa_china": [
        "china", "beijing", "xi jinping", "taiwan", "south china sea",
        "sino-us", "us-china", "chinese", "prc",
    ],
    "usa_europe": [
        "nato", "eu", "european union", "transatlantic", "brussels",
        "us-europe", "biden europe", "trump europe", "von der leyen",
    ],
    "tech_ai": [
        "artificial intelligence", "ai race", "semiconductor", "nvidia",
        "deepseek", "openai", "large language model", "chips act",
        "ai regulation", "machine learning", "generative ai",
    ],
    "usa_denmark": [
        "denmark", "greenland", "danish", "copenhagen", "mette frederiksen",
        "faroe islands", "denmark us", "us denmark",
    ],
    "europe_china": [
        "eu china", "europe china", "von der leyen china", "european china",
        "china europe trade", "brussels beijing",
    ],
    "supply_chain": [
        "rare earth", "tsmc", "lithium", "opec", "chip supply",
        "supply chain", "semiconductor supply", "critical minerals",
        "rare materials", "export controls",
    ],
    "energy_geo": [
        "lng", "nord stream", "energy security", "pipeline", "gas supply",
        "energy crisis", "natural gas", "oil price geopolitics",
        "energy independence", "fossil fuel",
    ],
}
