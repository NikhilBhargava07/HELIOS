"""Retrieve, sanitize, deduplicate, and age-filter Google News RSS items."""

import html
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

NEWS_LOOKBACK_DAYS = 30


def build_google_news_rss_url(query):
    """Build a localized Google News RSS search URL."""
    encoded_query = urllib.parse.quote(query)
    return f"https://news.google.com/rss/search?q={encoded_query}&hl=en-US&gl=US&ceid=US:en"


def clean_html_text(text):
    """Remove embedded tags and decode HTML entities from RSS text."""
    return html.unescape(re.sub(r"<[^>]+>", "", text or "")).strip()


def parse_news_datetime(value):
    """Parse an RSS publication date and normalize it to UTC."""
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def is_recent_news_item(item, now=None):
    """Return whether an item falls inside the configured news window."""
    published_at = parse_news_datetime(item.get("created_at"))
    current_time = now or datetime.now(timezone.utc)
    return bool(published_at and published_at >= current_time - timedelta(days=NEWS_LOOKBACK_DAYS))


def fetch_rss_news(query, limit=8):
    """Fetch and normalize a bounded set of RSS results for one query."""
    request = urllib.request.Request(
        build_google_news_rss_url(query),
        headers={"User-Agent": "Mozilla/5.0"},
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        root = ET.fromstring(response.read())

    items = []
    for item in root.findall("./channel/item")[:limit]:
        source = item.find("source")
        items.append({
            "headline": item.findtext("title", default=""),
            "summary": clean_html_text(item.findtext("description", default="")),
            "source": source.text if source is not None else "Google News",
            "url": item.findtext("link", default=""),
            "created_at": item.findtext("pubDate", default=None),
            "symbols": [],
            "query": query,
        })
    return items


def dedupe_news_items(news_items):
    """Remove repeated RSS results by URL while preserving order."""
    seen_urls = set()
    deduped = []
    for item in news_items:
        if item["url"] not in seen_urls:
            seen_urls.add(item["url"])
            deduped.append(item)
    return deduped


def get_recent_news(ticker_symbols, limit=12):
    """Collect current broad-market and company-specific headlines."""
    queries = [
        "US stock market latest news when:14d",
        "Federal Reserve inflation stocks latest when:14d",
        "AI stocks latest news when:14d",
        *(f"{ticker} stock latest news when:14d" for ticker in ticker_symbols[:8]),
    ]
    news_items = []
    for query in queries:
        try:
            news_items.extend(fetch_rss_news(query, limit=5))
        except Exception:
            continue

    recent = [item for item in dedupe_news_items(news_items) if is_recent_news_item(item)]
    recent.sort(
        key=lambda item: parse_news_datetime(item.get("created_at"))
        or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    return recent[:limit]
