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

def get_alpaca_credentials():
    ## Return Alpaca credentials from either supported environment naming style.
    api_key = os.getenv("APCA_API_KEY_ID") or os.getenv("ALPACA_API_KEY")
    secret_key = os.getenv("APCA_API_SECRET_KEY") or os.getenv("ALPACA_SECRET_KEY")
    if not api_key or not secret_key:
        raise ValueError("Missing Alpaca API credentials in .env")
    return api_key, secret_key


@lru_cache(maxsize=1)
def get_stock_data_client():
    ## Return a cached Alpaca stock-data client.
    api_key, secret_key = get_alpaca_credentials()
    return StockHistoricalDataClient(api_key, secret_key)


@lru_cache(maxsize=1)
def get_option_data_client():
    ## Return a cached Alpaca option-data client.
    api_key, secret_key = get_alpaca_credentials()
    return OptionHistoricalDataClient(api_key, secret_key)
