## Retrieve, sanitize, deduplicate, and age-filter Google News RSS items.

import html
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

NEWS_LOOKBACK_DAYS = 30
ESTABLISHED_NEWS_SOURCES = (
    "reuters", "associated press", "ap news", "bloomberg", "bbc",
    "financial times", "wall street journal", "cnbc", "marketwatch",
)


## Tag established reporting while leaving unfamiliar sources available.
def classify_source(source_name):
    normalized = (source_name or "").lower()
    return (
        "established_reporting"
        if any(name in normalized for name in ESTABLISHED_NEWS_SOURCES)
        else "unrated"
    )


## Build a localized Google News RSS search URL.
def build_google_news_rss_url(query):
    encoded_query = urllib.parse.quote(query)
    return f"https://news.google.com/rss/search?q={encoded_query}&hl=en-US&gl=US&ceid=US:en"


## Remove embedded tags and decode HTML entities from RSS text.
def clean_html_text(text):
    return html.unescape(re.sub(r"<[^>]+>", "", text or "")).strip()


## Parse an RSS publication date and normalize it to UTC.
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


## Return whether an item falls inside the configured news window.
def is_recent_news_item(item, now=None, lookback_days=NEWS_LOOKBACK_DAYS):
    published_at = parse_news_datetime(item.get("created_at"))
    current_time = now or datetime.now(timezone.utc)
    return bool(published_at and published_at >= current_time - timedelta(days=lookback_days))


## Fetch and normalize a bounded set of RSS results for one query.
def fetch_rss_news(query, limit=8):
    request = urllib.request.Request(
        build_google_news_rss_url(query),
        headers={"User-Agent": "Mozilla/5.0"},
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        root = ET.fromstring(response.read())

    items = []
    for item in root.findall("./channel/item")[:limit]:
        source = item.find("source")
        source_name = source.text if source is not None else "Google News"
        items.append({
            "headline": item.findtext("title", default=""),
            "summary": clean_html_text(item.findtext("description", default="")),
            "source": source_name,
            "source_quality": classify_source(source_name),
            "url": item.findtext("link", default=""),
            "created_at": item.findtext("pubDate", default=None),
            "symbols": [],
            "query": query,
        })
    return items


## Remove repeated RSS results by URL while preserving order.
def dedupe_news_items(news_items):
    seen_urls = set()
    deduped = []
    for item in news_items:
        if item["url"] not in seen_urls:
            seen_urls.add(item["url"])
            deduped.append(item)
    return deduped


## Collect current broad-market and company-specific headlines.
def get_recent_news(ticker_symbols, limit=12):
    specs = [
        ("US stock market latest news when:14d", []),
        ("Federal Reserve inflation stocks latest when:14d", []),
        ("geopolitical conflict war oil global markets when:14d", []),
        ("tariffs sanctions trade supply chains markets when:14d", []),
        ("government political leadership currency economy markets when:14d", []),
        ("AI stocks latest news when:14d", []),
        *((f"{ticker} stock latest news when:14d", [ticker]) for ticker in ticker_symbols[:8]),
    ]
    news_items = []
    with ThreadPoolExecutor(max_workers=min(8, len(specs))) as executor:
        for items in executor.map(_fetch_news_spec, specs):
            news_items.extend(items)

    recent = [item for item in dedupe_news_items(news_items) if is_recent_news_item(item)]
    recent.sort(
        key=lambda item: parse_news_datetime(item.get("created_at"))
        or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    return recent[:limit]


## Fetch one query and attach its related ticker symbols.
def _fetch_news_spec(spec):
    query, symbols = spec
    try:
        items = fetch_rss_news(query, limit=4)
    except Exception:
        return []
    for item in items:
        item["symbols"] = symbols
    return items


## Return ticker-tagged news and earnings evidence for CSP review.
def get_candidate_news(ticker_symbols, lookback_days=10, limit=36):
    unique_tickers = list(dict.fromkeys(ticker_symbols))
    specs = [
        (f"US stock market latest news when:{lookback_days}d", []),
        (f"Federal Reserve inflation stocks when:{lookback_days}d", []),
        (f"geopolitical conflict war oil global markets when:{lookback_days}d", []),
        (f"tariffs sanctions trade supply chains markets when:{lookback_days}d", []),
        (f"government political leadership currency economy markets when:{lookback_days}d", []),
        (f"energy prices inflation interest rates markets when:{lookback_days}d", []),
    ]
    for ticker in unique_tickers:
        specs.extend([
            (f"{ticker} stock latest news when:{lookback_days}d", [ticker]),
            (f"{ticker} earnings when:{lookback_days}d", [ticker]),
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
        key=lambda item: parse_news_datetime(item.get("created_at"))
        or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    selected = [item for item in recent if not item.get("symbols")][:10]
    for ticker in unique_tickers:
        selected.extend([
            item for item in recent
            if ticker in item.get("symbols", [])
        ][:2])
    return dedupe_news_items(selected)[:limit]
