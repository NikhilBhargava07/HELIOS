"""Build, filter, and rank cash-secured put candidates from Alpaca data."""

import pandas as pd
from datetime import datetime, timedelta

from alpaca.data.enums import DataFeed, OptionsFeed
from alpaca.data.requests import OptionChainRequest, StockLatestTradeRequest
from alpaca.trading.enums import ContractType
from backend.broker.clients import option_data_client, stock_data_client
from backend.strategy.dates import calculate_dte

def parse_option_symbol(contract_symbol):
    """Extract expiration and strike from an OCC option contract symbol."""
    option_code = contract_symbol[-15:]
    expiration = datetime.strptime(option_code[:6], "%y%m%d").date()
    strike = int(option_code[7:]) / 1000

    return expiration, strike


def get_latest_stock_price(ticker_symbol):
    """Fetch one ticker's latest IEX trade price."""
    request = StockLatestTradeRequest(
        symbol_or_symbols=ticker_symbol,
        feed=DataFeed.IEX,
    )

    latest_trades = stock_data_client.get_stock_latest_trade(request)

    return latest_trades[ticker_symbol].price


def build_put_rows_from_snapshots(ticker_symbol, snapshots, current_stock_price):
    """Convert Alpaca option snapshots into calculated candidate rows."""
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
                "tickerSymbol": ticker_symbol,
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
    """Score filtered puts using return, cushion, delta distance, and spread."""
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


def filter_valid_quotes(puts, max_spread, min_quote_size):
    """Remove missing, crossed, wide, or undersized option quotes."""
    return puts[
        (puts["bid"] > 0)
        & (puts["ask"] > 0)
        & (puts["spread"] > 0)
        & (puts["spread"] <= max_spread)
        & (puts["bidSize"] >= min_quote_size)
        & (puts["askSize"] >= min_quote_size)
    ]


def filter_by_delta(puts, target_delta, delta_tolerance):
    """Keep contracts inside the configured delta range."""
    min_delta = target_delta - delta_tolerance
    max_delta = target_delta + delta_tolerance

    return puts[
        (puts["delta"] >= min_delta)
        & (puts["delta"] <= max_delta)
    ]


def filter_by_iv(puts, min_iv_percent, max_iv_percent):
    """Keep contracts inside the acceptable implied-volatility range."""
    return puts[
        (puts["ivPercent"] >= min_iv_percent)
        & (puts["ivPercent"] <= max_iv_percent)
    ]


def filter_by_cash_required(puts, available_capital):
    """Keep contracts whose full cash collateral is affordable."""
    return puts[puts["cashRequired"] <= available_capital]


def filter_by_roc(puts, min_roc_percent):
    """Keep contracts meeting the minimum return-on-cash threshold."""
    return puts[puts["returnOnCashPercent"] >= min_roc_percent]


def apply_csp_filters(
    puts,
    target_delta,
    delta_tolerance,
    max_spread,
    min_quote_size,
    min_iv_percent,
    max_iv_percent,
    min_roc_percent,
    available_capital,
):
    """Apply all deterministic quote, risk, return, and capital filters."""
    filtered_puts = filter_valid_quotes(puts, max_spread, min_quote_size)
    filtered_puts = filter_by_delta(filtered_puts, target_delta, delta_tolerance)
    filtered_puts = filter_by_iv(filtered_puts, min_iv_percent, max_iv_percent)
    filtered_puts = filter_by_roc(filtered_puts, min_roc_percent)
    filtered_puts = filter_by_cash_required(filtered_puts, available_capital)

    return filtered_puts


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
    min_roc_percent,
    available_capital,
    current_stock_price=None,
):
    """Fetch a put chain and return its filtered, ranked CSP candidates."""
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
    if current_stock_price is None:
        current_stock_price = get_latest_stock_price(ticker_symbol)
    puts = build_put_rows_from_snapshots(ticker_symbol, snapshots, current_stock_price)

    if puts.empty:
        return pd.DataFrame()

    filtered_puts = apply_csp_filters(
        puts,
        target_delta,
        delta_tolerance,
        max_spread,
        min_quote_size,
        min_iv_percent,
        max_iv_percent,
        min_roc_percent,
        available_capital,
    )

    if filtered_puts.empty:
        return pd.DataFrame()

    ranked_puts = add_recommendation_score(filtered_puts, target_delta)

    display_columns = [
        "tickerSymbol",
        "contractSymbol",
        "expiration",
        "DTE",
        "strike",
        "currentStockPrice",
        "delta",
        "bid",
        "ask",
        "bidSize",
        "askSize",
        "spread",
        "ivPercent",
        "breakevenPrice",
        "premiumIfSoldAtBid",
        "cashRequired",
        "returnOnCashPercent",
        "score",
    ]

    return ranked_puts.sort_values(by="score", ascending=False)[display_columns]
