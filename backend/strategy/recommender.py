## Orchestrate one strategy's scan, ranking, and AI review.
##
## The module applies account-level limits, then asks the strategy for its
## candidates and the model for its judgment. It never assumes what is being
## traded: gathering candidates belongs to the strategy, so a chain scan and a
## batch of price history run through the same path.

import logging

import pandas as pd

from backend.capital import strategy_capacity
from backend.config import CAPITAL_BUDGETS, MAX_OPEN_POSITIONS
from backend.market.context import build_candidate_review_context
from backend.market.trends import get_latest_stock_prices
from backend.memory.learning_user import build_memory_context
from backend.strategy.ai_review import review_candidates
from backend.strategy.spec import ScanContext


logger = logging.getLogger(__name__)


## Check the hard position-count rule before recommending another position.
## The prototype avoids suggesting more exposure once the configured maximum is reached.
def can_open_new_position(current_open_positions, max_open_positions):
    return current_open_positions < max_open_positions


## Work out how much capital this strategy may still commit, honoring broker reality.
## Strategies secured by something other than cash have no budget and return None, meaning capital never limits them.
def available_strategy_capital(
    strategy,
    total_capital,
    committed_capital,
    external_available_capital=None,
):
    budget_percent = CAPITAL_BUDGETS.get(strategy.key)
    if budget_percent is None:
        return None

    _, available = strategy_capacity(
        total_capital,
        budget_percent,
        committed_capital,
    )
    if external_available_capital is not None:
        available = min(available, max(0, external_available_capital))

    return available


## Apply one strategy's account limits and return its ranked candidates, without asking the model anything.
##
## This is the deterministic half of a recommendation: limits, eligibility, the scan
## itself, and the ranking. It is separated because a scheduled triage needs these
## candidates from several strategies before making a single model call about all of
## them, and duplicating the limit rules for that path would be a second place to get
## them wrong. Returns (candidates, rejection); exactly one of the two is meaningful.
def rank_strategy_candidates(
    strategy,
    total_capital,
    current_open_positions=0,
    committed_capital=0,
    external_available_capital=None,
    portfolio_context=None,
    stock_data_client=None,
    option_data_client=None,
    limit=None,
):
    # Every strategy needs current prices. Anything further, such as an option chain,
    # is the strategy's own requirement and is checked where it is used.
    if stock_data_client is None:
        return None, _rejection("Broker market-data connection is not available.", f"Connect Alpaca before running {strategy.short_label} scans.")

    available_capital = available_strategy_capital(
        strategy,
        total_capital,
        committed_capital,
        external_available_capital,
    )
    commits_capital = available_capital is not None

    # The position cap limits new capital commitments. A strategy secured by shares
    # already owned commits none, and is bounded by the shares held instead.
    if commits_capital and not can_open_new_position(current_open_positions, MAX_OPEN_POSITIONS):
        return None, _rejection(f"Max open positions reached ({MAX_OPEN_POSITIONS}).", "Position limits prevent overcommitting the account.")

    if commits_capital and available_capital <= 0:
        return None, _rejection(f"No {strategy.short_label} capital available under current allocation rules.", "Capital rules keep the account from being overcommitted.")

    eligible_tickers = strategy.eligible_tickers(portfolio_context)
    if not eligible_tickers:
        return None, _rejection(
            f"No tickers currently qualify for a {strategy.short_label}.",
            f"A {strategy.short_label} requires {strategy.eligibility_requirement}.",
        )

    try:
        latest_prices = get_latest_stock_prices(eligible_tickers, stock_data_client=stock_data_client)
    except Exception as error:
        logger.warning("Latest stock-price lookup failed: %s", type(error).__name__)
        latest_prices = {}

    scan = strategy.find_candidates(
        strategy,
        eligible_tickers,
        ScanContext(
            available_capital=available_capital,
            latest_prices=latest_prices,
            portfolio_context=portfolio_context or {},
            stock_data_client=stock_data_client,
            option_data_client=option_data_client,
        ),
    )
    if scan.candidates.empty:
        error_note = (
            f" Market-data errors occurred for {len(scan.errors)} tickers."
            if scan.errors
            else ""
        )
        return None, _rejection(
            f"No {strategy.short_label} candidates found across approved tickers.",
            f"The current filters may be too strict for today's market data.{error_note}",
        )

    ranked = (
        scan.candidates.sort_values(by=strategy.rank_column, ascending=False)
        if strategy.rank_column
        else scan.candidates
    )
    keep = limit or strategy.max_candidates

    return (ranked.head(keep) if keep else ranked), None


## Orchestrate one full recommendation run from broker state to saved AI review.
## The function gathers capital, candidates, context, memory, and model review for the API route.
def get_recommendation_results(
    strategy,
    user_id,
    total_capital,
    current_open_positions=0,
    committed_capital=0,
    external_available_capital=None,
    portfolio_context=None,
    stock_data_client=None,
    option_data_client=None,
):
    top_candidates, rejection = rank_strategy_candidates(
        strategy,
        total_capital,
        current_open_positions=current_open_positions,
        committed_capital=committed_capital,
        external_available_capital=external_available_capital,
        portfolio_context=portfolio_context,
        stock_data_client=stock_data_client,
        option_data_client=option_data_client,
    )
    if rejection:
        return rejection

    candidate_tickers = top_candidates["tickerSymbol"].drop_duplicates().tolist()
    open_position_tickers = [
        position.get("ticker_symbol")
        for position in (portfolio_context or {}).get("open_csp_positions", [])
        if position.get("ticker_symbol")
    ]
    context_tickers = list(dict.fromkeys([
        *candidate_tickers,
        *open_position_tickers,
    ]))
    market_context = build_candidate_review_context(
        context_tickers,
        stock_data_client=stock_data_client,
    )
    try:
        memory_context = build_memory_context(user_id, candidate_tickers)
    except Exception as error:
        logger.warning("Memory retrieval failed: %s", type(error).__name__)
        memory_context = {
            "relevant_episodes": [],
            "outcome_patterns": [],
            "user_profile": None,
            "memory_error": "Long-term memory unavailable.",
        }
    review = review_candidates(
        strategy,
        "top filtered ticker set",
        top_candidates,
        market_context=market_context,
        portfolio_context=portfolio_context,
        memory_context=memory_context,
    )
    return {
        "candidates": top_candidates,
        "review": review,
        "market_context": market_context,
        "portfolio_context": portfolio_context or {},
        "memory_context": memory_context,
    }


## Build a standard reject-all response when strategy constraints block new trades.
## Returning the same structure as a normal review keeps frontend rendering simple.
def _rejection(summary, risk_note):
    return {
        "candidates": pd.DataFrame(),
        "review": {
            "decision": "reject_all",
            "selected_contract": None,
            "summary": summary,
            "risk_note": risk_note,
        },
    }
