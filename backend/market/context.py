"""Assemble price trends and current news into one AI-ready market context."""

from backend.market.news import get_recent_news
from backend.market.trends import get_market_trends


def build_market_context(ticker_symbols):
    """Return current trends and news while preserving a recoverable news error."""
    trends = get_market_trends(ticker_symbols)
    try:
        news = get_recent_news(ticker_symbols)
        news_error = None
    except Exception as error:
        news = []
        news_error = str(error)
    return {"trends": trends, "news": news, "news_error": news_error}
