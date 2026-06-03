import pandas as pd
from datetime import datetime, timedelta

from alpaca.data.enums import OptionsFeed
from alpaca.data.requests import OptionChainRequest
from alpaca.trading.enums import ContractType
from alpaca_clients import option_data_client
from dte import *

def parse_option_symbol(contract_symbol):
    option_code = contract_symbol[-15:]
    expiration = datetime.strptime(option_code[:6], "%y%m%d").date()
    strike = int(option_code[7:]) / 1000

    return expiration, strike


def build_put_rows_from_snapshots(snapshots):
    rows = []

    for contract_symbol, snapshot in snapshots.items():
        quote = snapshot.latest_quote
        greeks = snapshot.greeks

        if quote is None:
            continue

        expiration, strike = parse_option_symbol(contract_symbol)
        expiration_text = expiration.strftime("%Y-%m-%d")
        bid = quote.bid_price
        ask = quote.ask_price

        rows.append(
            {
                "contractSymbol": contract_symbol,
                "expiration": expiration_text,
                "DTE": calculate_dte(expiration_text),
                "strike": strike,
                "bid": bid,
                "ask": ask,
                "spread": ask - bid,
                "volume": None,
                "openInterest": None,
                "impliedVolatility": snapshot.implied_volatility,
                "ivPercent": snapshot.implied_volatility * 100 if snapshot.implied_volatility else None,
                "delta": greeks.delta if greeks else None,
                "cashRequired": strike * 100,
                "premiumIfSoldAtBid": bid * 100,
            }
        )

    return pd.DataFrame(rows)


def find_csp_candidates(ticker_symbol, min_dte, max_dte, min_volume, min_open_interest):
    today = datetime.today().date()
    min_expiration = (today + timedelta(days=min_dte)).strftime("%Y-%m-%d")
    max_expiration = (today + timedelta(days=max_dte)).strftime("%Y-%m-%d")

    request = OptionChainRequest(
        underlying_symbol=ticker_symbol,
        type=ContractType.PUT,
        feed=OptionsFeed.INDICATIVE,
        expiration_date_gte=min_expiration,
        expiration_date_lte=max_expiration,
    )

    snapshots = option_data_client.get_option_chain(request)
    puts = build_put_rows_from_snapshots(snapshots)

    if puts.empty:
        return pd.DataFrame()

    filtered_puts = puts[
        (puts["bid"] > 0)
        & (puts["ask"] > 0)
        & (puts["spread"] > 0)
        & (puts["spread"] <= 0.50)
    ]

    columns = [
        "contractSymbol",
        "expiration",
        "DTE",
        "strike",
        "bid",
        "ask",
        "spread",
        "volume",
        "openInterest",
        "ivPercent",
        "delta",
        "cashRequired",
        "premiumIfSoldAtBid",
    ]

    return filtered_puts[columns].sort_values(by=["DTE", "strike"])
