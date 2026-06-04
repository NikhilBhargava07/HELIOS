import pandas as pd
from datetime import datetime, timedelta

from alpaca.data.enums import DataFeed, OptionsFeed
from alpaca.data.requests import OptionChainRequest, StockLatestTradeRequest
from alpaca.trading.enums import ContractType
from alpaca_clients import option_data_client, stock_data_client
from dte import *

def parse_option_symbol(contract_symbol):
    option_code = contract_symbol[-15:]
    expiration = datetime.strptime(option_code[:6], "%y%m%d").date()
    strike = int(option_code[7:]) / 1000

    return expiration, strike


def get_latest_stock_price(ticker_symbol):
    request = StockLatestTradeRequest(
        symbol_or_symbols=ticker_symbol,
        feed=DataFeed.IEX,
    )

    latest_trades = stock_data_client.get_stock_latest_trade(request)

    return latest_trades[ticker_symbol].price


def build_put_rows_from_snapshots(snapshots, current_stock_price):
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
        dte = calculate_dte(expiration_text)
        cash_required = strike * 100
        premium_if_sold_at_bid = bid * 100
        breakeven_price = strike - bid
        return_on_cash = premium_if_sold_at_bid / cash_required
        percent_otm = ((current_stock_price - strike) / current_stock_price) * 100

        rows.append(
            {
                "contractSymbol": contract_symbol,
                "expiration": expiration_text,
                "DTE": dte,
                "strike": strike,
                "currentStockPrice": current_stock_price,
                "percentOTM": percent_otm,
                "bid": bid,
                "ask": ask,
                "spread": ask - bid,
                "bidSize": quote.bid_size,
                "askSize": quote.ask_size,
                "impliedVolatility": snapshot.implied_volatility,
                "ivPercent": snapshot.implied_volatility * 100 if snapshot.implied_volatility else None,
                "delta": greeks.delta if greeks else None,
                "breakevenPrice": breakeven_price,
                "cashRequired": cash_required,
                "premiumIfSoldAtBid": premium_if_sold_at_bid,
                "returnOnCashPercent": return_on_cash * 100,
                "annualizedReturnPercent": return_on_cash * (365 / dte) * 100 if dte > 0 else None,
            }
        )

    return pd.DataFrame(rows)


def add_recommendation_score(puts, target_delta):
    puts = puts.copy()
    puts["deltaDistance"] = (puts["delta"] - target_delta).abs()
    puts["spreadPercentOfBid"] = (puts["spread"] / puts["bid"]) * 100

    puts["score"] = (
        puts["annualizedReturnPercent"]
        + puts["ivPercent"] * 0.10
        + puts["percentOTM"] * 0.50
        - puts["deltaDistance"] * 100
        - puts["spreadPercentOfBid"] * 0.25
    )

    return puts


def find_csp_candidates(
    ticker_symbol,
    min_dte,
    max_dte,
    target_delta,
    delta_tolerance,
    max_spread,
    min_quote_size,
    min_iv_percent,
    max_iv_percent,
    available_capital,
):
    today = datetime.today().date()
    min_expiration = (today + timedelta(days=min_dte)).strftime("%Y-%m-%d")
    max_expiration = (today + timedelta(days=max_dte)).strftime("%Y-%m-%d")
    min_delta = target_delta - delta_tolerance
    max_delta = target_delta + delta_tolerance

    request = OptionChainRequest(
        underlying_symbol=ticker_symbol,
        type=ContractType.PUT,
        feed=OptionsFeed.INDICATIVE,
        expiration_date_gte=min_expiration,
        expiration_date_lte=max_expiration,
    )

    snapshots = option_data_client.get_option_chain(request)
    current_stock_price = get_latest_stock_price(ticker_symbol)
    puts = build_put_rows_from_snapshots(snapshots, current_stock_price)

    if puts.empty:
        return pd.DataFrame()

    filtered_puts = puts[
        (puts["bid"] > 0)
        & (puts["ask"] > 0)
        & (puts["spread"] > 0)
        & (puts["spread"] <= max_spread)
        & (puts["bidSize"] >= min_quote_size)
        & (puts["askSize"] >= min_quote_size)
        & (puts["delta"] >= min_delta)
        & (puts["delta"] <= max_delta)
        & (puts["ivPercent"] >= min_iv_percent)
        & (puts["ivPercent"] <= max_iv_percent)
        & (puts["cashRequired"] <= available_capital)
    ]

    if filtered_puts.empty:
        return pd.DataFrame()

    ranked_puts = add_recommendation_score(filtered_puts, target_delta)

    display_columns = [
        "contractSymbol",
        "expiration",
        "DTE",
        "strike",
        "currentStockPrice",
        "delta",
        "bid",
        "ask",
        "spread",
        "ivPercent",
        "breakevenPrice",
        "premiumIfSoldAtBid",
        "cashRequired",
        "returnOnCashPercent",
    ]

    return ranked_puts.sort_values(by="score", ascending=False)[display_columns]
