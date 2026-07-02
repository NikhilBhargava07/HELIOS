## Create authenticated Alpaca market-data clients shared by the application.
##
## Clients are created lazily so importing backend modules does not immediately
## require broker credentials. That keeps local scripts, tests, and future Lambda
## cold starts easier to reason about.

import os
from functools import lru_cache

from alpaca.data.historical import (
    StockHistoricalDataClient,
    OptionHistoricalDataClient,
)

## Load Alpaca API credentials from environment variables only.
## Keeping credentials out of frontend code and source files protects the paper-trading account during local and AWS deployments.
def get_alpaca_credentials():
    api_key = os.getenv("APCA_API_KEY_ID") or os.getenv("ALPACA_API_KEY")
    secret_key = os.getenv("APCA_API_SECRET_KEY") or os.getenv("ALPACA_SECRET_KEY")
    if not api_key or not secret_key:
        raise ValueError("Missing Alpaca API credentials in .env")
    return api_key, secret_key


## Return a cached Alpaca stock-data client.
@lru_cache(maxsize=1)
## Create an Alpaca stock data client for quotes, bars, and latest prices.
## The client is built from environment credentials whenever market data needs to be fetched.
def get_stock_data_client():
    api_key, secret_key = get_alpaca_credentials()
    return StockHistoricalDataClient(api_key, secret_key)


## Return a cached Alpaca option-data client.
@lru_cache(maxsize=1)
## Create an Alpaca option data client for option-chain snapshots.
## Candidate generation depends on this client for put quotes, greeks, implied volatility, and liquidity fields.
def get_option_data_client():
    api_key, secret_key = get_alpaca_credentials()
    return OptionHistoricalDataClient(api_key, secret_key)
