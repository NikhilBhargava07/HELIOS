## Rank filtered contracts and produce the candidate table one strategy offers for review.
##
## This is the pipeline every option strategy runs: fetch the chain, attach the
## strategy's economics, enforce the hard rules, score what is left, and return
## the columns that strategy displays.

import logging
import time
from concurrent.futures import ThreadPoolExecutor

import pandas as pd

from backend.config import (
    CANDIDATES_PER_TICKER,
    MAX_PARALLEL_TICKER_SCANS,
    MINIMUM_EXPECTED_MOVE_PERCENT,
    RATE_LIMIT_RETRY_SECONDS,
)
from backend.strategy.engine.filters import apply_option_filters
from backend.strategy.engine.option_chain import (
    build_candidate_rows,
    fetch_option_snapshots,
    get_latest_stock_price,
)
from backend.strategy.spec import ScanResult


logger = logging.getLogger(__name__)


## Add a ranking score once every hard metric is present.
##
## Reward and cushion are both measured against the move the market expects, rather
## than in raw percent. The delta filter already pins every surviving candidate to
## roughly the same chance of assignment, so what separates them is not how likely
## assignment is but how far the stock keeps going once it happens. Ranking on raw
## premium therefore picked the widest tail available and called it the best trade,
## which is how one volatile name came to fill a whole day's recommendations.
##
## Distance from the money is normalized for the same reason. At a fixed delta a more
## volatile stock's strike sits further out, so rewarding raw distance was a second
## way of rewarding volatility. Expressed in expected moves, it measures real cushion.
def add_recommendation_score(contracts, target_delta):
    contracts = contracts.copy()
    contracts["deltaDistance"] = (contracts["delta"] - target_delta).abs()
    contracts["spreadPercentOfBid"] = (contracts["spread"] / contracts["bid"]) * 100

    # How far the market expects this stock to travel over the life of the contract.
    # Implied volatility is annual, so it is scaled to the time actually at risk.
    contracts["expectedMovePercent"] = (
        contracts["ivPercent"] * ((contracts["DTE"] / 365) ** 0.5)
    ).clip(lower=MINIMUM_EXPECTED_MOVE_PERCENT)

    # Premium earned per unit of expected move, and strike distance in expected moves.
    contracts["returnPerExpectedMove"] = (
        contracts["returnOnCashPercent"] / contracts["expectedMovePercent"]
    )
    contracts["cushionInExpectedMoves"] = (
        contracts["percentOTM"] / contracts["expectedMovePercent"]
    )

    contracts["score"] = (
        contracts["returnPerExpectedMove"] * 100
        + contracts["cushionInExpectedMoves"] * 5
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


## Recognize the broker throttling a burst of requests.
## Told apart from a real failure because a throttled ticker is worth asking for again, while a broken one is not.
def _is_rate_limited(error):
    if getattr(error, "status_code", None) == 429:
        return True

    message = str(error).lower()

    return "429" in message or "rate limit" in message or "too many requests" in message


## Scan one ticker without letting its failure end the scan of every other one.
##
## The candidates and the error come back together rather than as an exception,
## because a worker raising would abandon the tickers queued behind it. A
## throttled request is retried once, since scanning in parallel makes throttling
## likely enough that dropping the ticker would quietly narrow the choice.
def _scan_one_ticker(strategy, ticker_symbol, context):
    for attempt in range(2):
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
            return candidates, None
        except Exception as error:
            if attempt == 0 and _is_rate_limited(error):
                logger.info("Option scan for %s was rate-limited; retrying once", ticker_symbol)
                time.sleep(RATE_LIMIT_RETRY_SECONDS)
                continue

            logger.warning("Option scan failed for %s: %s", ticker_symbol, type(error).__name__)
            return pd.DataFrame(), f"{ticker_symbol}:{type(error).__name__}"


## Scan every eligible ticker's option chain and return the candidates they yield.
##
## Each ticker is a separate broker request whose time is spent waiting on the
## network, so the requests overlap instead of queueing: fetching fifty-six chains
## one after another was the bulk of a scan's minute. The Alpaca client is shared
## across the workers, which its connection pool is built for, and the worker count
## stays below that pool's size.
##
## Results are reassembled in the order the tickers were given, so the same account
## and the same market produce the same ranking no matter which response arrives
## first. Only each ticker's best few contracts continue, because otherwise one
## liquid chain could crowd every other ticker out of the model's view.
def find_option_candidates(strategy, ticker_symbols, context):
    if context.option_data_client is None:
        raise ValueError("Explicit Alpaca market-data clients are required for option scans.")

    ticker_symbols = list(ticker_symbols)
    if not ticker_symbols:
        return ScanResult(candidates=pd.DataFrame())

    started_at = time.monotonic()
    with ThreadPoolExecutor(max_workers=min(MAX_PARALLEL_TICKER_SCANS, len(ticker_symbols))) as executor:
        scans = list(executor.map(
            lambda ticker_symbol: _scan_one_ticker(strategy, ticker_symbol, context),
            ticker_symbols,
        ))

    frames = []
    errors = []
    for candidates, error in scans:
        if error:
            errors.append(error)
        elif not candidates.empty:
            frames.append(candidates.head(CANDIDATES_PER_TICKER))

    logger.info(
        "Scanned %s %s chains in %.2fs: %s with candidates, %s unreadable",
        len(ticker_symbols),
        strategy.key,
        time.monotonic() - started_at,
        len(frames),
        len(errors),
    )

    return ScanResult(
        candidates=pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(),
        errors=tuple(errors),
    )
