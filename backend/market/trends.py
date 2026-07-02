## Fetch Alpaca price history and calculate multi-period market trends.

from datetime import datetime, timedelta, timezone

from alpaca.data.enums import DataFeed
from alpaca.data.requests import StockBarsRequest, StockLatestTradeRequest
from alpaca.data.timeframe import TimeFrame

from backend.broker.clients import get_stock_data_client

TREND_PERIODS = {"1d": 1, "5d": 5, "2w": 14, "1m": 30, "ytd": "ytd"}
DEFAULT_TREND_PERIODS = ["1d", "5d", "2w", "1m", "ytd"]


## Calculate percentage movement between two prices.
## Trend cards and AI context use this for 1-day, 5-day, 2-week, 1-month, and YTD comparisons.
def calculate_percent_change(start_price, end_price):
    return None if not start_price else ((end_price - start_price) / start_price) * 100


## Translate a trend window label into the historical start date to request.
## Centralizing windows keeps the trend API and UI labels aligned.
def get_start_date(period):
    today = datetime.now(timezone.utc)
    if period == "ytd":
        return datetime(today.year, 1, 1, tzinfo=timezone.utc)
    return today - timedelta(days=TREND_PERIODS[period] + 7)


## Fetch historical bars and summarize one ticker’s trend windows.
## The result includes percent and dollar changes so the UI can rotate between both views.
def build_price_trend(ticker_symbol, period, ticker_bars):
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


## Build trend summaries for the approved ticker universe.
## Failures for one ticker are skipped so a single market-data issue does not break the whole page.
def get_market_trends(ticker_symbols, periods=None):
    periods = periods or DEFAULT_TREND_PERIODS
    stock_data_client = get_stock_data_client()
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


## Convert Alpaca timestamps into JSON-safe text.
## This keeps latest-price responses serializable across local FastAPI and Lambda.
def serialize_timestamp(value):
    if value is None:
        return None
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


## Fetch current prices for the approved ticker list.
## The frontend calls this frequently to refresh price pills without rebuilding full trend history.
def get_latest_stock_prices(ticker_symbols):
    stock_data_client = get_stock_data_client()
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
