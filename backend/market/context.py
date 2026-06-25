## Assemble price trends and current news into one AI-ready market context.

import logging

from backend.market.news import get_candidate_news, get_recent_news
from backend.market.trends import get_market_trends


MARKET_BENCHMARKS = ["SPY", "QQQ", "IWM"]
logger = logging.getLogger(__name__)


## Return current trends and news while preserving a recoverable news error.
def build_market_context(ticker_symbols):
    trends = get_market_trends(ticker_symbols)
    try:
        news = get_recent_news(ticker_symbols)
        news_error = None
    except Exception as error:
        logger.warning("Market news lookup failed: %s", type(error).__name__)
        news = []
        news_error = "Market news unavailable."
    return {"trends": trends, "news": news, "news_error": news_error}


## Build ten-day company evidence plus benchmark and ticker trends.
def build_candidate_review_context(ticker_symbols):
    candidate_tickers = list(dict.fromkeys(ticker_symbols))
    trend_tickers = list(dict.fromkeys([*MARKET_BENCHMARKS, *candidate_tickers]))
    try:
        trends = get_market_trends(trend_tickers)
        trends_error = None
    except Exception as error:
        logger.warning("Market trend lookup failed: %s", type(error).__name__)
        trends = []
        trends_error = "Market trends unavailable."
    try:
        news = get_candidate_news(candidate_tickers, lookback_days=10)
        news_error = None
    except Exception as error:
        logger.warning("Candidate news lookup failed: %s", type(error).__name__)
        news = []
        news_error = "Candidate news unavailable."
    return {
        "candidate_tickers": candidate_tickers,
        "news_and_earnings_lookback_days": 10,
        "trends": trends,
        "news_and_earnings": news,
        "trends_error": trends_error,
        "news_error": news_error,
    }
