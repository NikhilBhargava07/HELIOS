"""Create authenticated Alpaca market-data clients shared by the application."""

import os
from dotenv import load_dotenv
from alpaca.data.historical import (
    StockHistoricalDataClient,
    OptionHistoricalDataClient,
)

from backend.config import PROJECT_ROOT

load_dotenv(PROJECT_ROOT / ".env")

API_KEY = os.getenv("APCA_API_KEY_ID")
SECRET_KEY = os.getenv("APCA_API_SECRET_KEY")

if not API_KEY or not SECRET_KEY:
    raise ValueError("Missing Alpaca API credentials in .env")

stock_data_client = StockHistoricalDataClient(API_KEY, SECRET_KEY)
option_data_client = OptionHistoricalDataClient(API_KEY, SECRET_KEY)
