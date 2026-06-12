import json
import os
import html
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

from alpaca.data.enums import DataFeed
from alpaca.data.requests import StockBarsRequest, StockLatestTradeRequest
from alpaca.data.timeframe import TimeFrame
from dotenv import load_dotenv

from alpaca_clients import stock_data_client


load_dotenv(Path(__file__).with_name(".env"))

OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.5")
NEWS_LOOKBACK_DAYS = 30
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
            "dollar_change": None,
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
        "dollar_change": end_bar.close - start_bar.close,
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
                ticker_trend[f"{period}_dollar"] = trend["dollar_change"]
            except Exception as error:
                ticker_trend[period] = None
                ticker_trend[f"{period}_dollar"] = None
                ticker_trend[f"{period}_error"] = str(error)

        trends.append(ticker_trend)

    return trends


def serialize_timestamp(value):
    if value is None:
        return None

    if hasattr(value, "isoformat"):
        return value.isoformat()

    return str(value)


def get_latest_stock_prices(ticker_symbols):
    request = StockLatestTradeRequest(
        symbol_or_symbols=ticker_symbols,
        feed=DataFeed.IEX,
    )
    latest_trades = stock_data_client.get_stock_latest_trade(request)
    prices = {}

    for ticker_symbol in ticker_symbols:
        trade = latest_trades.get(ticker_symbol)

        if not trade:
            prices[ticker_symbol] = {
                "price": None,
                "timestamp": None,
            }
            continue

        prices[ticker_symbol] = {
            "price": trade.price,
            "timestamp": serialize_timestamp(trade.timestamp),
        }

    return prices


def build_google_news_rss_url(query):
    encoded_query = urllib.parse.quote(query)

    return f"https://news.google.com/rss/search?q={encoded_query}&hl=en-US&gl=US&ceid=US:en"


def clean_html_text(text):
    text = re.sub(r"<[^>]+>", "", text or "")

    return html.unescape(text).strip()


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


def is_recent_news_item(item, now=None):
    if now is None:
        now = datetime.now(timezone.utc)

    published_at = parse_news_datetime(item.get("created_at"))

    if published_at is None:
        return False

    return published_at >= now - timedelta(days=NEWS_LOOKBACK_DAYS)


def fetch_rss_news(query, limit=8):
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
        "US stock market latest news when:14d",
        "Federal Reserve inflation stocks latest when:14d",
        "AI stocks latest news when:14d",
    ]

    for ticker_symbol in ticker_symbols[:8]:
        queries.append(f"{ticker_symbol} stock latest news when:14d")

    news_items = []

    for query in queries:
        try:
            news_items.extend(fetch_rss_news(query, limit=5))
        except Exception:
            continue

    recent_news_items = [
        item
        for item in dedupe_news_items(news_items)
        if is_recent_news_item(item)
    ]
    recent_news_items.sort(
        key=lambda item: parse_news_datetime(item.get("created_at")) or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )

    return recent_news_items[:limit]


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
            "headline": "No market context yet.",
            "market_mood": "Neutral",
            "csp_stance": "Wait",
            "reasoned_take": "Load trends and news before leaning on the market take. Without current context, the safest answer is to rely only on the hard CSP filters and avoid making a market call.",
            "csp_take": "Use only the hard CSP filters for now.",
            "action": "Review filtered CSP candidates normally.",
            "avoid": "Do not force a trade without context.",
            "company_notes": [],
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
        "headline": "Use trend data as a risk check.",
        "market_mood": "Mixed",
        "csp_stance": "Selective",
        "reasoned_take": (
            "The approved list is not moving as one group, which usually means selectivity matters more than reaching for premium. "
            f"The strongest recent names include {', '.join(row['ticker'] for row in strongest)}, while {', '.join(row['ticker'] for row in weakest)} look weaker on the 5-day view. "
            "For CSPs, that means the better paper trades are likely the ones with clean filters, enough downside cushion, and stocks you would actually accept owning."
        ),
        "csp_take": "Favor CSPs only when hard filters pass.",
        "action": "Prefer names you are comfortable owning.",
        "avoid": "Avoid chasing high IV after sharp moves.",
        "company_notes": [
            {
                "ticker": row["ticker"],
                "note": "Stronger 5-day trend; still check spread, IV, and downside cushion.",
            }
            for row in strongest
        ],
        "scenarios": [
            f"Stronger 5-day names: {', '.join(row['ticker'] for row in strongest)}.",
            f"Weaker 5-day names: {', '.join(row['ticker'] for row in weakest)}.",
            "Scenario context, not a price prediction.",
        ],
    }


def parse_market_take_json(text):
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?", "", cleaned)
    cleaned = re.sub(r"```$", "", cleaned).strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)

        if not match:
            raise

        return json.loads(match.group(0))


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
Return only valid JSON with these keys:
- headline: max 8 words
- market_mood: one of "Calm", "Mixed", "Choppy", "Risky"
- csp_stance: one of "Favorable", "Selective", "Cautious", "Wait"
- reasoned_take: 3 to 5 sentences. Give a real opinion using the news and trend data. Mention specific tickers/companies from context and explain why they matter. Keep it understandable for a newer options learner.
- csp_take: 1 to 2 sentences, framed around CSP paper trading
- action: max 24 words, what the user should prioritize
- avoid: max 24 words, what the user should avoid
- company_notes: 2 to 4 objects with keys ticker and note. Each note should explain why that company looks interesting, volatile, weak, or worth watching based on trends/news.
- scenarios: exactly 3 strings, each max 20 words

Avoid empty buzzwords like "macro uncertainty" unless you explain what that means in plain language.
Do not say a stock "will" rise or fall. Say "could", "may", "looks", or "seems" because this is not prediction software.
If news mentions a product, earnings, AI demand, regulation, rates, inflation, or geopolitics, connect that to the relevant company/ticker.

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

        take = parse_market_take_json(response.output_text)

        return {
            "headline": take.get("headline", "Market risk check"),
            "market_mood": take.get("market_mood", "Mixed"),
            "csp_stance": take.get("csp_stance", "Selective"),
            "reasoned_take": take.get("reasoned_take", take.get("summary", "")),
            "csp_take": take.get("csp_take", ""),
            "action": take.get("action", ""),
            "avoid": take.get("avoid", ""),
            "company_notes": take.get("company_notes", [])[:4],
            "scenarios": take.get("scenarios", [])[:3],
        }
    except Exception as error:
        fallback = local_market_take(context)
        fallback["reasoned_take"] = f"AI failed, so local fallback was used: {error}"

        return fallback
