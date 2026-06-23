"""Create authenticated Alpaca market-data clients shared by the application."""

import os
from alpaca.data.historical import (
    StockHistoricalDataClient,
    OptionHistoricalDataClient,
)

def get_alpaca_credentials():
    """Return Alpaca credentials from either supported environment naming style."""
    api_key = os.getenv("APCA_API_KEY_ID") or os.getenv("ALPACA_API_KEY")
    secret_key = os.getenv("APCA_API_SECRET_KEY") or os.getenv("ALPACA_SECRET_KEY")
    if not api_key or not secret_key:
        raise ValueError("Missing Alpaca API credentials in .env")
    return api_key, secret_key


API_KEY, SECRET_KEY = get_alpaca_credentials()

stock_data_client = StockHistoricalDataClient(API_KEY, SECRET_KEY)
option_data_client = OptionHistoricalDataClient(API_KEY, SECRET_KEY)
