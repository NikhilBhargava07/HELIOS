## Rank filtered contracts and produce the candidate table one strategy offers for review.
##
## This is the pipeline every option strategy runs: fetch the chain, attach the
## strategy's economics, enforce the hard rules, score what is left, and return
## the columns that strategy displays.

import pandas as pd

from backend.strategy.engine.filters import apply_option_filters
from backend.strategy.engine.option_chain import (
    build_candidate_rows,
    fetch_option_snapshots,
    get_latest_stock_price,
)


## Add a ranking score once every hard metric is present.
## The score favors cleaner setups near target delta, with tighter spreads, acceptable IV, and stronger return.
def add_recommendation_score(contracts, target_delta):
    contracts = contracts.copy()
    contracts["deltaDistance"] = (contracts["delta"] - target_delta).abs()
    contracts["spreadPercentOfBid"] = (contracts["spread"] / contracts["bid"]) * 100

    contracts["score"] = (
        contracts["annualizedReturnPercent"]
        + contracts["ivPercent"] * 0.10
        + contracts["percentOTM"] * 0.50
        - contracts["deltaDistance"] * 100
        - contracts["spreadPercentOfBid"] * 0.25
    )

    return contracts


## Scan one ticker for contracts that satisfy a strategy's rules, ranked best first.
##
## Strategies whose economics depend on account state, such as a covered call
## needing the cost basis of shares already held, pass a pre-bound economics
## function instead of the strategy default.
def find_option_candidates(
    strategy,
    ticker_symbol,
    available_capital,
    current_stock_price=None,
    stock_data_client=None,
    option_data_client=None,
    economics=None,
):
    if stock_data_client is None or option_data_client is None:
        raise ValueError("Explicit Alpaca market-data clients are required for option scans.")

    snapshots = fetch_option_snapshots(
        ticker_symbol,
        strategy.contract_type,
        strategy.rules.min_dte,
        strategy.rules.max_dte,
        option_data_client,
    )
    if current_stock_price is None:
        current_stock_price = get_latest_stock_price(ticker_symbol, stock_data_client)

    contracts = build_candidate_rows(
        ticker_symbol,
        snapshots,
        current_stock_price,
        economics or strategy.economics,
    )
    if contracts.empty:
        return pd.DataFrame()

    filtered = apply_option_filters(
        contracts,
        strategy.rules,
        strategy.capital_column,
        available_capital,
    )
    if filtered.empty:
        return pd.DataFrame()

    ranked = add_recommendation_score(filtered, strategy.rules.target_delta)

    return ranked.sort_values(by="score", ascending=False)[list(strategy.display_columns)]
