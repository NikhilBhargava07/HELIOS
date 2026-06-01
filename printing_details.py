import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
from csp_candidates import *
from dte import *

from alpaca.data.enums import DataFeed, OptionsFeed
from alpaca.data.requests import StockLatestTradeRequest, OptionChainRequest
from alpaca.trading.enums import ContractType
from alpaca_clients import stock_data_client, option_data_client

def print_stock_price(ticker_symbol: str):
    request = StockLatestTradeRequest(
        symbol_or_symbols=ticker_symbol,
        feed=DataFeed.IEX,
    )

    latest_trades = stock_data_client.get_stock_latest_trade(request)
    current_price = latest_trades[ticker_symbol].price

    print(f"{ticker_symbol} latest trade price: ${current_price:.2f}")


def print_option_expirations(ticker_symbol: str):
    # Create a ticker object
    ticker = yf.Ticker(ticker_symbol)

    # Get all available option expiration dates
    expirations = ticker.options
    print(f"\nAvailable option expirations for {ticker_symbol}:")

    for exp in expirations[:10]:
        print("-", exp)
    return expirations


def print_option_chain(ticker_symbol: str, expiration: str):
    # Create a ticker object
    ticker = yf.Ticker(ticker_symbol)

    # Pull the full options chain for the given expiration date
    chain = ticker.option_chain(expiration)

    # Separate the chain into calls and puts
    calls = chain.calls.copy()
    puts = chain.puts.copy()

    dte = calculate_dte(expiration)

    # Add DTE column
    calls["DTE"] = dte
    puts["DTE"] = dte

    # Calculated columns for ease of analysis
    calls["spread"] = calls["ask"] - calls["bid"]
    calls["iv_percent"] = calls["impliedVolatility"] * 100

    # Columns we care about for now
    columns = [
        "contractSymbol",
        "strike",
        "lastTransactionPrice",
        "bid",
        "ask",
        "spread",
        "volume",
        "openInterest",
        "impliedVolatility",
        "iv_percent",
        "DTE"
    ]

    ##print(f"\nCALL OPTIONS for {ticker_symbol}, expiration {expiration}:")
    ##print(calls[columns].head(20))
    ##print(f"\nPUT OPTIONS for {ticker_symbol}, expiration {expiration}:")
    ##print(puts[columns].head(20))
    print(calls[["strike", "bid", "ask", "spread", "volume", "openInterest", "impliedVolatility","iv_percent", "DTE"]])


def print_alpaca_put_chain(ticker_symbol: str):
    request = OptionChainRequest(
        underlying_symbol=ticker_symbol,
        type=ContractType.PUT,
        feed=OptionsFeed.INDICATIVE,
    )

    snapshots = option_data_client.get_option_chain(request)

    print(f"\nSample Alpaca put options for {ticker_symbol}:")

    for contract_symbol, snapshot in list(snapshots.items())[:10]:
        quote = snapshot.latest_quote
        greeks = snapshot.greeks

        bid = quote.bid_price if quote else None
        ask = quote.ask_price if quote else None
        delta = greeks.delta if greeks else None

        print(
            f"{contract_symbol} | "
            f"bid: {bid} | "
            f"ask: {ask} | "
            f"IV: {snapshot.implied_volatility} | "
            f"delta: {delta}"
        )