## Create Alpaca market-data clients from explicit credentials.
##
## HELIOS no longer reads APCA/ALPACA keys from .env for normal app behavior.
## User-facing routes load broker credentials from the signed-in user profile and pass them into these constructors.

from alpaca.data.historical import (
    StockHistoricalDataClient,
    OptionHistoricalDataClient,
)


## Create an Alpaca stock-data client from explicit credentials.
## Future authenticated routes use this with broker credentials loaded from the signed-in user's profile.
def create_stock_data_client(api_key, secret_key):
    return StockHistoricalDataClient(api_key, secret_key)


## Create an Alpaca option-data client from explicit credentials.
## Keeping this separate from trading clients makes the per-user market-data path straightforward.
def create_option_data_client(api_key, secret_key):
    return OptionHistoricalDataClient(api_key, secret_key)
