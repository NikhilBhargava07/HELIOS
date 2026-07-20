## Orchestrate CSP scanning, ranking, and AI review.
##
## The module applies account-level limits before asking the candidate engine to
## scan each approved ticker. The AI receives only contracts that already passed
## the deterministic strategy rules.

import logging

import pandas as pd

from backend.config import (
    APPROVED_TICKERS, CANDIDATES_PER_TICKER, DELTA_TOLERANCE, MAX_DTE,
    MAX_IV_PERCENT, MAX_OPEN_POSITIONS, MAX_RECOMMENDATIONS, MAX_SPREAD,
    MAX_CSP_CAPITAL_PERCENT, MIN_DTE, MIN_IV_PERCENT, MIN_QUOTE_SIZE,
    MIN_ROC_PERCENT, STRATEGY_RULES, TARGET_DELTA,
)
from backend.strategy.ai_review import review_csp_candidates
from backend.strategy.candidates import find_csp_candidates
from backend.market.context import build_candidate_review_context
from backend.market.trends import get_latest_stock_prices
from backend.memory.learning_user import build_memory_context


logger = logging.getLogger(__name__)


## Check the hard position-count rule before recommending another CSP.
## The prototype avoids suggesting new exposure once the configured maximum number of open CSPs is reached.
def can_open_new_position(current_open_positions, max_open_positions):
    return current_open_positions < max_open_positions


## Calculate how much CSP capital remains under the hard allocation rule.
## This is separate from Alpaca buying power because strategy capacity and broker capacity are both relevant.
def calculate_available_csp_capital(
    total_capital,
    max_csp_capital_percent,
    current_csp_capital_committed,
):
    max_csp_capital = total_capital * max_csp_capital_percent
    return max(0, max_csp_capital - current_csp_capital_committed)


## Orchestrate one full recommendation run from broker state to saved AI review.
## The function gathers capital, candidates, context, memory, model review, and dashboard data for the API route.
def get_recommendation_results(
    user_id,
    total_capital,
    current_open_positions=0,
    current_csp_capital_committed=0,
    external_available_csp_capital=None,
    portfolio_context=None,
    stock_data_client=None,
    option_data_client=None,
):
    if stock_data_client is None or option_data_client is None:
        return _rejection("Broker market-data connection is not available.", "Connect Alpaca before running CSP scans.")

    if not can_open_new_position(current_open_positions, MAX_OPEN_POSITIONS):
        return _rejection(f"Max open positions reached ({MAX_OPEN_POSITIONS}).", "Position limits prevent overcommitting the account.")

    available_capital = calculate_available_csp_capital(
        total_capital,
        MAX_CSP_CAPITAL_PERCENT,
        current_csp_capital_committed,
    )
    if external_available_csp_capital is not None:
        available_capital = min(available_capital, max(0, external_available_csp_capital))

    if available_capital <= 0:
        return _rejection("No CSP capital available under current allocation rules.", "Capital rules keep the account from being overcommitted.")

    try:
        latest_prices = get_latest_stock_prices(APPROVED_TICKERS, stock_data_client=stock_data_client)
    except Exception as error:
        logger.warning("Latest stock-price lookup failed: %s", type(error).__name__)
        latest_prices = {}

    candidate_frames = []
    scan_errors = []
    for ticker_symbol in APPROVED_TICKERS:
        try:
            candidates = find_csp_candidates(
                ticker_symbol, MIN_DTE, MAX_DTE, TARGET_DELTA, DELTA_TOLERANCE,
                MAX_SPREAD, MIN_QUOTE_SIZE, MIN_IV_PERCENT, MAX_IV_PERCENT,
                MIN_ROC_PERCENT, available_capital,
                current_stock_price=(latest_prices.get(ticker_symbol) or {}).get("price"),
                stock_data_client=stock_data_client,
                option_data_client=option_data_client,
            )
        except Exception as error:
            scan_errors.append(f"{ticker_symbol}:{type(error).__name__}")
            continue

        if not candidates.empty:
            candidate_frames.append(candidates.head(CANDIDATES_PER_TICKER))

    if not candidate_frames:
        error_note = (
            f" Market-data errors occurred for {len(scan_errors)} tickers."
            if scan_errors
            else ""
        )
        return _rejection(
            "No CSP candidates found across approved tickers.",
            f"The current filters may be too strict for today's market data.{error_note}",
        )

    combined = pd.concat(candidate_frames, ignore_index=True)
    top_candidates = combined.sort_values(by="score", ascending=False).head(MAX_RECOMMENDATIONS)
    candidate_tickers = top_candidates["tickerSymbol"].drop_duplicates().tolist()
    market_context = build_candidate_review_context(candidate_tickers, stock_data_client=stock_data_client)
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
    review = review_csp_candidates(
        "top filtered ticker set",
        top_candidates,
        STRATEGY_RULES,
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
