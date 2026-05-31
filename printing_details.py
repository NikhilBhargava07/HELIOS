import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
from csp_candidates import *
from dte import *

def print_stock_price(ticker_symbol: str):
    # Create a yfinance ticker object for the stock
    ticker = yf.Ticker(ticker_symbol)

    # Get the most recent 1 day of price history
    history = ticker.history(period="1d")

    # If yfinance returns no data, stop the function
    if history.empty:
        print(f"No price data found for {ticker_symbol}")
        return

    # Grab the latest closing price from the history table
    current_price = history["Close"].iloc[-1]
    print(f"{ticker_symbol} current price: ${current_price:.2f}")


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
