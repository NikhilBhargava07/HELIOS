## Rank filtered contracts and produce the candidate table one strategy offers for review.
##
## This is the pipeline every option strategy runs: fetch the chain, attach the
## strategy's economics, enforce the hard rules, score what is left, and return
## the columns that strategy displays.

import logging

import pandas as pd

from backend.config import CANDIDATES_PER_TICKER
from backend.strategy.engine.filters import apply_option_filters
from backend.strategy.engine.option_chain import (
    build_candidate_rows,
    fetch_option_snapshots,
    get_latest_stock_price,
)
from backend.strategy.spec import ScanResult


logger = logging.getLogger(__name__)


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
def scan_ticker_option_chain(
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
        strategy.extra_filters,
    )
    if filtered.empty:
        return pd.DataFrame()

    ranked = add_recommendation_score(filtered, strategy.rules.target_delta)

    return ranked.sort_values(by="score", ascending=False)[list(strategy.display_columns)]


## Scan every eligible ticker's option chain and return the candidates they yield.
##
## Each ticker is a separate broker request, so one that fails is recorded and
## skipped: a single unreadable chain should not end a scan of the whole universe.
## Only each ticker's best few contracts continue, because otherwise one liquid
## chain could crowd every other ticker out of the model's view.
def find_option_candidates(strategy, ticker_symbols, context):
    if context.option_data_client is None:
        raise ValueError("Explicit Alpaca market-data clients are required for option scans.")

    frames = []
    errors = []

    for ticker_symbol in ticker_symbols:
        try:
            candidates = scan_ticker_option_chain(
                strategy,
                ticker_symbol,
                context.available_capital,
                current_stock_price=(context.latest_prices.get(ticker_symbol) or {}).get("price"),
                stock_data_client=context.stock_data_client,
                option_data_client=context.option_data_client,
                economics=(
                    strategy.bind_economics(ticker_symbol, context.portfolio_context)
                    if strategy.bind_economics
                    else None
                ),
            )
        except Exception as error:
            logger.warning("Option scan failed for %s: %s", ticker_symbol, type(error).__name__)
            errors.append(f"{ticker_symbol}:{type(error).__name__}")
            continue

        if not candidates.empty:
            frames.append(candidates.head(CANDIDATES_PER_TICKER))

    return ScanResult(
        candidates=pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(),
        errors=tuple(errors),
    )
