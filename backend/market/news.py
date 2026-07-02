## Retrieve, score, sanitize, deduplicate, and age-filter Google News RSS items.
##
## The news tab is the evidence layer for HELIOS. It should surface current,
## reputable market and company catalysts while avoiding low-quality SEO feeds.
## The AI review/take prompts then reason from this supplied evidence.

import html
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

from backend.config import COMPANY_NAMES


NEWS_LOOKBACK_DAYS = 14
CANDIDATE_NEWS_LOOKBACK_DAYS = 10
RSS_TIMEOUT_SECONDS = 8

TRUSTED_NEWS_SOURCES = (
    "reuters", "associated press", "ap news", "bloomberg",
    "financial times", "wall street journal", "wsj",
)

ESTABLISHED_NEWS_SOURCES = (
    "cnbc", "marketwatch", "barron's", "barrons", "dow jones",
    "the information", "axios", "the verge", "techcrunch",
    "semafor", "fortune", "forbes", "investopedia", "morningstar",
    "yahoo finance", "investor's business daily", "investors business daily",
)

LOW_QUALITY_NEWS_SOURCES = (
    "gurufocus", "z2news", "insider monkey", "benzinga",
    "tipranks", "simply wall st", "marketbeat", "stocktitan",
    "zacks", "seeking alpha", "247wallst", "24/7 wall", "thefly",
    "ticker report", "stocktwits", "international business times",
)

MAJOR_NEWS_TICKERS = (
    "AAPL", "MSFT", "NVDA", "META", "AMZN", "GOOGL", "TSLA", "AMD",
    "AVGO", "ORCL", "NFLX", "CSCO", "CRM", "INTC", "MU", "QCOM",
    "JPM", "WMT", "COST", "NKE", "PLTR", "SOFI",
)

CATALYST_KEYWORDS = {
    "layoffs": (
        "layoff", "layoffs", "job cuts", "job cut", "cuts jobs",
        "workforce reduction", "restructuring", "headcount reduction",
    ),
    "earnings": (
        "earnings", "quarterly results", "revenue", "profit", "eps",
        "quarter", "results",
    ),
    "guidance": ("guidance", "outlook", "forecast", "warns", "warning"),
    "ai": (
        "artificial intelligence", " ai ", "data center", "datacenter",
        "gpu", "chips", "semiconductor", "infrastructure",
    ),
    "market_move": (
        "shares rise", "shares fall", "stock jumps", "stock drops",
        "surges", "plunges", "rally", "selloff", "sell-off", "dips",
    ),
    "macro": (
        "federal reserve", "fed", "inflation", "interest rates", "rates",
        "jobs report", "treasury yields", "cpi", "pce", "recession",
    ),
    "geopolitical": (
        "war", "conflict", "oil", "tariff", "tariffs", "sanctions",
        "iran", "middle east", "china", "russia", "supply chain",
    ),
    "product": ("launch", "unveils", "release", "product", "upgrade"),
    "regulation": (
        "regulator", "regulatory", "antitrust", "lawsuit", "probe",
        "investigation", "sec", "ftc", "doj",
    ),
    "deal": ("deal", "partnership", "acquisition", "merger", "investment"),
}

HIGH_PRIORITY_TAGS = {"layoffs", "earnings", "guidance", "regulation", "geopolitical"}


## Label each news source by reputation tier.
## HELIOS uses this to prioritize established sources and filter out low-quality feeds.
def classify_source(source_name):
    normalized = (source_name or "").lower()
    if any(source in normalized for source in LOW_QUALITY_NEWS_SOURCES):
        return "excluded_low_quality"
    if any(source in normalized for source in TRUSTED_NEWS_SOURCES):
        return "trusted_reporting"
    if any(source in normalized for source in ESTABLISHED_NEWS_SOURCES):
        return "established_reporting"
    return "unrated"


## Build a Google News RSS search URL for a market or ticker query.
## RSS lets the prototype gather current headlines without storing API keys for a paid news provider yet.
def build_google_news_rss_url(query):
    encoded_query = urllib.parse.quote(query)
    return f"https://news.google.com/rss/search?q={encoded_query}&hl=en-US&gl=US&ceid=US:en"


## Strip HTML markup and excess whitespace from RSS summaries.
## Clean text improves both frontend readability and LLM prompt quality.
def clean_html_text(text):
    return html.unescape(re.sub(r"<[^>]+>", "", text or "")).strip()


## Parse RSS publication timestamps into timezone-aware datetimes.
## Recency checks depend on consistent datetime objects across news feeds.
def parse_news_datetime(value):
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


## Decide whether a headline is fresh enough for market context.
## The news tab focuses on current conditions, so older items are filtered unless the feed timestamp is missing.
def is_recent_news_item(item, now=None, lookback_days=NEWS_LOOKBACK_DAYS):
    published_at = parse_news_datetime(item.get("created_at"))
    current_time = now or datetime.now(timezone.utc)
    return bool(published_at and published_at >= current_time - timedelta(days=lookback_days))


## Normalize a headline for deduplication.
## RSS searches can return the same story through multiple query paths, so titles need a stable comparison key.
def normalize_headline(headline):
    return re.sub(r"[^a-z0-9]+", " ", (headline or "").lower()).strip()


## Infer which approved tickers are connected to a headline.
## The UI and prompts use these symbols to connect company-specific news with CSP candidates.
def infer_related_symbols(item, query_symbols):
    related = set(query_symbols or [])
    text = f" {item.get('headline', '')} {item.get('summary', '')} ".lower()
    for ticker, company_name in COMPANY_NAMES.items():
        if len(ticker) < 2 and ticker not in related:
            continue
        ticker_pattern = rf"(?<![a-z0-9]){re.escape(ticker.lower())}(?![a-z0-9])"
        company_tokens = company_name.lower().split()
        company_key = " ".join(company_tokens[:2]) if len(company_tokens) > 1 else company_name.lower()
        if re.search(ticker_pattern, text) or company_key in text:
            related.add(ticker)
    return sorted(related)


## Assign practical market-impact tags to a news item.
## Tags such as earnings, layoffs, rates, or geopolitics help users quickly see why a headline matters.
def classify_news_tags(item):
    text = f" {item.get('headline', '')} {item.get('summary', '')} ".lower()
    tags = [
        tag for tag, keywords in CATALYST_KEYWORDS.items()
        if any(keyword in text for keyword in keywords)
    ]
    return tags or ["market_context"]


## Create a short beginner-friendly explanation for why a headline matters.
## This gives the News tab useful context without turning it into a long AI market take.
def explain_news_relevance(item):
    tags = set(item.get("tags", []))
    symbols = item.get("symbols", [])
    subject = ", ".join(symbols[:3]) if symbols else "the market"

    if "layoffs" in tags:
        return f"Layoffs or restructuring can change sentiment and volatility for {subject}, so CSP assignment risk deserves extra attention."
    if "earnings" in tags or "guidance" in tags:
        return f"Earnings and guidance can quickly reprice {subject}, which matters during a put contract's lifetime."
    if "regulation" in tags:
        return f"Regulatory news can create headline risk for {subject}, even when option premium looks attractive."
    if "geopolitical" in tags:
        return "Geopolitical and trade headlines can affect rates, oil, supply chains, and overall investor risk appetite."
    if "ai" in tags:
        return f"AI and infrastructure news can move large tech names and change option premium quickly."
    if "market_move" in tags:
        return f"Large price moves can make premium richer, but they can also signal higher downside risk."
    return "Use this as current context before trusting a CSP recommendation."


## Score one news item by source quality, recency, ticker relevance, and market-impact tags.
## Higher-scoring articles appear first and are more likely to enter the LLM evidence package.
def score_news_item(item, query_priority=1):
    source_score = {
        "trusted_reporting": 25,
        "established_reporting": 16,
        "unrated": 4,
    }.get(item.get("source_quality"), 0)
    tag_score = sum(8 if tag in HIGH_PRIORITY_TAGS else 4 for tag in item.get("tags", []))
    symbol_score = 8 if item.get("symbols") else 0
    published_at = parse_news_datetime(item.get("created_at"))
    recency_score = 0
    if published_at:
        age_hours = (datetime.now(timezone.utc) - published_at).total_seconds() / 3600
        recency_score = max(0, 14 - int(age_hours // 24))
    return source_score + tag_score + symbol_score + recency_score + query_priority


## Fetch and normalize RSS items for one search specification.
## Network and parsing failures return an empty list so the broader news request can continue.
def fetch_rss_news(query, limit=8):
    request = urllib.request.Request(
        build_google_news_rss_url(query),
        headers={"User-Agent": "Mozilla/5.0"},
    )
    with urllib.request.urlopen(request, timeout=RSS_TIMEOUT_SECONDS) as response:
        root = ET.fromstring(response.read())

    items = []
    for item in root.findall("./channel/item")[:limit]:
        source = item.find("source")
        source_name = source.text if source is not None else "Google News"
        source_quality = classify_source(source_name)
        if source_quality == "excluded_low_quality":
            continue
        items.append({
            "headline": clean_html_text(item.findtext("title", default="")),
            "summary": clean_html_text(item.findtext("description", default="")),
            "source": source_name,
            "source_quality": source_quality,
            "url": item.findtext("link", default=""),
            "created_at": item.findtext("pubDate", default=None),
            "symbols": [],
            "tags": [],
            "why_it_matters": "",
            "query": query,
            "category": "general",
            "relevance_score": 0,
        })
    return items


## Remove duplicate headlines while keeping the highest-scored version.
## This prevents the news page and LLM prompt from repeating the same story.
def dedupe_news_items(news_items):
    seen_urls = set()
    seen_headlines = set()
    deduped = []
    for item in sorted(news_items, key=lambda row: row.get("relevance_score", 0), reverse=True):
        url = item.get("url", "")
        headline_key = normalize_headline(item.get("headline", ""))
        if url in seen_urls or headline_key in seen_headlines:
            continue
        seen_urls.add(url)
        seen_headlines.add(headline_key)
        deduped.append(item)
    return deduped


## Worker helper for concurrently fetching one news search spec.
## Keeping this tiny helper separate makes threaded RSS fetching easier to read.
def _fetch_news_spec(spec):
    query, symbols, category, priority = spec
    try:
        items = fetch_rss_news(query, limit=4)
    except Exception:
        return []
    for item in items:
        item["category"] = category
        item["symbols"] = infer_related_symbols(item, symbols)
        item["tags"] = classify_news_tags(item)
        item["why_it_matters"] = explain_news_relevance(item)
        item["relevance_score"] = score_news_item(item, priority)
    return items


## Collect the current market news feed shown on the News tab.
## Results are filtered to reputable, recent, market-relevant articles before being returned.
def get_recent_news(ticker_symbols, limit=18):
    company_tickers = list(dict.fromkeys([
        ticker for ticker in (*MAJOR_NEWS_TICKERS, *ticker_symbols)
        if ticker in COMPANY_NAMES
    ]))[:24]
    specs = [
        ("stock market today Reuters Bloomberg CNBC Fed inflation when:14d", [], "broad_market", 10),
        ("S&P 500 Nasdaq megacap technology stocks when:14d", [], "broad_market", 8),
        ("AI infrastructure data center chip stocks Reuters Bloomberg when:14d", [], "tech_ai", 10),
        ("Federal Reserve inflation jobs yields stocks Reuters CNBC when:14d", [], "macro", 9),
        ("geopolitical oil tariffs sanctions global markets Reuters when:14d", [], "geopolitical", 8),
        ("corporate earnings guidance layoffs stocks Reuters Bloomberg CNBC when:14d", [], "company_catalysts", 9),
    ]
    specs.extend(
        (f"{ticker} stock news earnings guidance layoffs AI when:14d", [ticker], "company", 7)
        for ticker in company_tickers
    )

    news_items = []
    with ThreadPoolExecutor(max_workers=min(8, len(specs))) as executor:
        for items in executor.map(_fetch_news_spec, specs):
            news_items.extend(items)

    recent = [
        item for item in dedupe_news_items(news_items)
        if is_recent_news_item(item) and item.get("source_quality") != "excluded_low_quality"
    ]
    recent.sort(
        key=lambda item: (
            item.get("relevance_score", 0),
            parse_news_datetime(item.get("created_at"))
            or datetime.min.replace(tzinfo=timezone.utc),
        ),
        reverse=True,
    )
    return recent[:limit]


## Collect recent news for the tickers currently being reviewed as CSP candidates.
## The recommendation prompt uses this to discuss company-specific catalysts and risks.
def get_candidate_news(ticker_symbols, lookback_days=CANDIDATE_NEWS_LOOKBACK_DAYS, limit=36):
    unique_tickers = list(dict.fromkeys(ticker_symbols))
    specs = [
        (f"stock market today Fed inflation yields when:{lookback_days}d", [], "broad_market", 8),
        (f"geopolitical oil tariffs sanctions markets when:{lookback_days}d", [], "geopolitical", 7),
        (f"AI infrastructure tech stocks when:{lookback_days}d", [], "tech_ai", 7),
        (f"earnings guidance layoffs stocks when:{lookback_days}d", [], "company_catalysts", 8),
    ]
    for ticker in unique_tickers:
        specs.extend([
            (f"{ticker} stock latest news when:{lookback_days}d", [ticker], "company", 10),
            (f"{ticker} earnings guidance when:{lookback_days}d", [ticker], "earnings", 10),
            (f"{ticker} layoffs restructuring regulation when:{lookback_days}d", [ticker], "risk_catalyst", 9),
        ])

    news_items = []
    with ThreadPoolExecutor(max_workers=min(8, len(specs))) as executor:
        for items in executor.map(_fetch_news_spec, specs):
            news_items.extend(items)

    recent = [
        item for item in dedupe_news_items(news_items)
        if is_recent_news_item(item, lookback_days=lookback_days)
    ]
    recent.sort(
        key=lambda item: (
            item.get("relevance_score", 0),
            parse_news_datetime(item.get("created_at"))
            or datetime.min.replace(tzinfo=timezone.utc),
        ),
        reverse=True,
    )

    selected = [item for item in recent if not item.get("symbols")][:8]
    for ticker in unique_tickers:
        selected.extend([
            item for item in recent
            if ticker in item.get("symbols", [])
        ][:3])
    return dedupe_news_items(selected)[:limit]
