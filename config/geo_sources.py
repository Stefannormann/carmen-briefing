"""Geopolitical RSS sources and topic tier configuration."""

GEO_TOPIC_TIER_1 = ["usa_china", "usa_europe", "tech_ai"]
GEO_TOPIC_TIER_2 = ["usa_denmark", "europe_china", "supply_chain", "energy_geo"]

GEO_RSS_TIER_1 = [
    "https://feeds.reuters.com/reuters/worldNews",
    "https://rss.scmp.com/rss/91",
    "https://foreignpolicy.com/feed",
    "https://feeds.reuters.com/Reuters/worldNewsEurope",
    "https://www.politico.eu/feed",
    "https://feeds.apnews.com/rss/worldnews",
    "https://www.technologyreview.com/feed",
    "https://www.theverge.com/rss/ai/index.xml",
    "https://feeds.reuters.com/reuters/technologyNews",
]

GEO_RSS_TIER_2 = [
    "https://www.dr.dk/nyheder/service/feeds/allenyheder",
    "https://politiken.dk/rss",
    "https://cphpost.dk/?feed=rss2",
    "https://www.altinget.dk/feed",
    "https://www.euractiv.com/feed/",
    "https://feeds.reuters.com/reuters/companyNews",
    "https://www.aljazeera.com/xml/rss/all.xml",
    "https://www.euractiv.com/sections/energy/feed/",
    "https://techcrunch.com/feed/",
    "https://feeds.arstechnica.com/arstechnica/index",
]

# Sources that publish in Danish — headlines/summaries translated via Gemini before scoring
DANISH_LANGUAGE_SOURCES = [
    "https://www.dr.dk/nyheder/service/feeds/allenyheder",
    "https://politiken.dk/rss",
    "https://www.altinget.dk/feed",
]
