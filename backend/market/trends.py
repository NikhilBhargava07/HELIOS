"""Fetch Alpaca price history and calculate multi-period market trends."""

from datetime import datetime, timedelta, timezone

from alpaca.data.enums import DataFeed
from alpaca.data.requests import StockBarsRequest, StockLatestTradeRequest
from alpaca.data.timeframe import TimeFrame

from backend.broker.clients import stock_data_client

TREND_PERIODS = {"1d": 1, "5d": 5, "2w": 14, "1m": 30, "ytd": "ytd"}
DEFAULT_TREND_PERIODS = ["1d", "5d", "2w", "1m", "ytd"]


def calculate_percent_change(start_price, end_price):
    """Return percentage movement between two prices."""
    return None if not start_price else ((end_price - start_price) / start_price) * 100


def get_start_date(period):
    """Return a UTC history start date with enough buffer for a trend period."""
    today = datetime.now(timezone.utc)
    if period == "ytd":
        return datetime(today.year, 1, 1, tzinfo=timezone.utc)
    return today - timedelta(days=TREND_PERIODS[period] + 7)


def build_price_trend(ticker_symbol, period, ticker_bars):
    """Calculate one trend from already-fetched daily bars."""
    if len(ticker_bars) < 2:
        return {
            "ticker": ticker_symbol, "period": period, "start_price": None,
            "end_price": None, "dollar_change": None, "percent_change": None,
        }

    end_bar = ticker_bars[-1]
    if period == "ytd":
        start_bar = ticker_bars[0]
    else:
        start_index = max(0, len(ticker_bars) - TREND_PERIODS[period] - 1)
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
    """Fetch one batched YTD history request and calculate all requested periods."""
    periods = periods or DEFAULT_TREND_PERIODS
    request = StockBarsRequest(
        symbol_or_symbols=ticker_symbols,
        timeframe=TimeFrame.Day,
        start=get_start_date("ytd"),
        feed=DataFeed.IEX,
    )
    bars = stock_data_client.get_stock_bars(request)
    trends = []
    for ticker_symbol in ticker_symbols:
        ticker_trend = {"ticker": ticker_symbol}
        for period in periods:
            try:
                trend = build_price_trend(ticker_symbol, period, bars.data.get(ticker_symbol, []))
                ticker_trend[period] = trend["percent_change"]
                ticker_trend[f"{period}_dollar"] = trend["dollar_change"]
            except Exception as error:
                ticker_trend[period] = None
                ticker_trend[f"{period}_dollar"] = None
                ticker_trend[f"{period}_error"] = str(error)
        trends.append(ticker_trend)
    return trends


def serialize_timestamp(value):
    """Convert an Alpaca timestamp into JSON-safe text."""
    if value is None:
        return None
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def get_latest_stock_prices(ticker_symbols):
    """Fetch latest IEX trades for every requested symbol in one request."""
    request = StockLatestTradeRequest(symbol_or_symbols=ticker_symbols, feed=DataFeed.IEX)
    latest_trades = stock_data_client.get_stock_latest_trade(request)
    prices = {}
    for ticker_symbol in ticker_symbols:
        trade = latest_trades.get(ticker_symbol)
        prices[ticker_symbol] = {
            "price": trade.price if trade else None,
            "timestamp": serialize_timestamp(trade.timestamp) if trade else None,
        }
    return prices
