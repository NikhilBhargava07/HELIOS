import json
import os
import html
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

from alpaca.data.enums import DataFeed
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from dotenv import load_dotenv

from alpaca_clients import stock_data_client


load_dotenv(Path(__file__).with_name(".env"))

OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.5")
TREND_PERIODS = {
    "1d": 1,
    "5d": 5,
    "2w": 14,
    "1m": 30,
    "ytd": "ytd",
}


def calculate_percent_change(start_price, end_price):
    if not start_price:
        return None

    return ((end_price - start_price) / start_price) * 100


def get_start_date(period):
    today = datetime.now(timezone.utc)

    if period == "ytd":
        return datetime(today.year, 1, 1, tzinfo=timezone.utc)

    return today - timedelta(days=TREND_PERIODS[period] + 7)


def get_price_trend(ticker_symbol, period):
    request = StockBarsRequest(
        symbol_or_symbols=ticker_symbol,
        timeframe=TimeFrame.Day,
        start=get_start_date(period),
        feed=DataFeed.IEX,
    )
    bars = stock_data_client.get_stock_bars(request)
    ticker_bars = bars.data.get(ticker_symbol, [])

    if len(ticker_bars) < 2:
        return {
            "ticker": ticker_symbol,
            "period": period,
            "start_price": None,
            "end_price": None,
            "percent_change": None,
        }

    end_bar = ticker_bars[-1]

    if period == "ytd":
        start_bar = ticker_bars[0]
    else:
        lookback_days = TREND_PERIODS[period]
        start_index = max(0, len(ticker_bars) - lookback_days - 1)
        start_bar = ticker_bars[start_index]

    return {
        "ticker": ticker_symbol,
        "period": period,
        "start_price": start_bar.close,
        "end_price": end_bar.close,
        "percent_change": calculate_percent_change(start_bar.close, end_bar.close),
    }


def get_market_trends(ticker_symbols, periods=None):
    if periods is None:
        periods = ["1d", "5d", "2w", "1m", "ytd"]

    trends = []

    for ticker_symbol in ticker_symbols:
        ticker_trend = {"ticker": ticker_symbol}

        for period in periods:
            try:
                trend = get_price_trend(ticker_symbol, period)
                ticker_trend[period] = trend["percent_change"]
            except Exception as error:
                ticker_trend[period] = None
                ticker_trend[f"{period}_error"] = str(error)

        trends.append(ticker_trend)

    return trends


def build_google_news_rss_url(query):
    encoded_query = urllib.parse.quote(query)

    return f"https://news.google.com/rss/search?q={encoded_query}&hl=en-US&gl=US&ceid=US:en"


def clean_html_text(text):
    text = re.sub(r"<[^>]+>", "", text or "")

    return html.unescape(text).strip()


def fetch_rss_news(query, limit=5):
    url = build_google_news_rss_url(query)
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0"},
    )

    with urllib.request.urlopen(request, timeout=10) as response:
        rss_xml = response.read()

    root = ET.fromstring(rss_xml)
    items = []

    for item in root.findall("./channel/item")[:limit]:
        source = item.find("source")

        items.append(
            {
                "headline": item.findtext("title", default=""),
                "summary": clean_html_text(item.findtext("description", default="")),
                "source": source.text if source is not None else "Google News",
                "url": item.findtext("link", default=""),
                "created_at": item.findtext("pubDate", default=None),
                "symbols": [],
                "query": query,
            }
        )

    return items


def dedupe_news_items(news_items):
    seen_urls = set()
    deduped = []

    for item in news_items:
        url = item["url"]

        if url in seen_urls:
            continue

        seen_urls.add(url)
        deduped.append(item)

    return deduped


def get_recent_news(ticker_symbols, limit=12):
    queries = [
        "US stock market latest news when:7d",
        "Federal Reserve inflation stocks latest when:7d",
        "AI stocks latest news when:7d",
    ]

    for ticker_symbol in ticker_symbols[:8]:
        queries.append(f"{ticker_symbol} stock latest news when:7d")

    news_items = []

    for query in queries:
        try:
            news_items.extend(fetch_rss_news(query, limit=3))
        except Exception:
            continue

    return dedupe_news_items(news_items)[:limit]


def build_market_context(ticker_symbols):
    trends = get_market_trends(ticker_symbols)

    try:
        news = get_recent_news(ticker_symbols)
    except Exception as error:
        news = []
        news_error = str(error)
    else:
        news_error = None

    return {
        "trends": trends,
        "news": news,
        "news_error": news_error,
    }


def local_market_take(context):
    if not context["trends"] and not context["news"]:
        return {
            "summary": "No market context is available yet.",
            "csp_take": "Use only the hard CSP filters until trend/news data is available.",
            "scenarios": [
                "Neutral: continue reviewing filtered CSP candidates only.",
            ],
        }

    strongest = sorted(
        context["trends"],
        key=lambda row: row.get("5d") if row.get("5d") is not None else -999,
        reverse=True,
    )[:3]
    weakest = sorted(
        context["trends"],
        key=lambda row: row.get("5d") if row.get("5d") is not None else 999,
    )[:3]

    return {
        "summary": "Local fallback take based on recent trend data.",
        "csp_take": (
            "Favor CSPs only when the hard filters pass and the stock is one you are comfortable owning. "
            "Treat sharp recent moves or high IV as reasons to inspect risk more carefully."
        ),
        "scenarios": [
            f"Stronger 5-day names: {', '.join(row['ticker'] for row in strongest)}.",
            f"Weaker 5-day names: {', '.join(row['ticker'] for row in weakest)}.",
            "This is scenario context, not a price prediction.",
        ],
    }


def ai_market_take(context):
    if not os.getenv("OPENAI_API_KEY"):
        return local_market_take(context)

    try:
        from openai import OpenAI
    except ImportError:
        return local_market_take(context)

    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    prompt = f"""
You are helping with an educational cash-secured put paper-trading dashboard.

Review the trend and news context below. Do not pretend to know the future.
Give a concise market take framed as CSP risk context:
- summary
- csp_take
- three scenario bullets for the next few weeks

Context:
{json.dumps(context, indent=2)}
"""

    try:
        response = client.responses.create(
            model=OPENAI_MODEL,
            input=[
                {
                    "role": "system",
                    "content": "You are a cautious market-context assistant for CSP paper trading.",
                },
                {
                    "role": "user",
                    "content": prompt,
                },
            ],
        )

        return {
            "summary": response.output_text,
            "csp_take": "Use this context to inspect assignment risk, not to predict exact prices.",
            "scenarios": [
                "Bullish/steady: CSPs may collect premium if hard filters still pass.",
                "Choppy: prioritize tighter spreads, lower deltas, and stocks you are comfortable owning.",
                "Bearish: assignment risk rises; consider passing even if premiums look attractive.",
            ],
        }
    except Exception as error:
        fallback = local_market_take(context)
        fallback["summary"] = f"AI market take failed, so local fallback was used. Error: {error}"

        return fallback
