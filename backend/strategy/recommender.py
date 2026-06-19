"""Orchestrate CSP scanning, ranking, and AI review.

The module applies account-level limits before asking the candidate engine to
scan each approved ticker. The AI receives only contracts that already passed
the deterministic strategy rules.
"""

import pandas as pd

from backend.config import (
    APPROVED_TICKERS, CANDIDATES_PER_TICKER, DELTA_TOLERANCE, MAX_DTE,
    MAX_IV_PERCENT, MAX_OPEN_POSITIONS, MAX_RECOMMENDATIONS, MAX_SPREAD,
    MAX_CSP_CAPITAL_PERCENT, MIN_DTE, MIN_IV_PERCENT, MIN_QUOTE_SIZE,
    MIN_ROC_PERCENT, STRATEGY_RULES, TARGET_DELTA, TOTAL_CAPITAL,
)
from backend.strategy.ai_review import review_csp_candidates
from backend.strategy.candidates import find_csp_candidates, get_latest_stock_prices


def can_open_new_position(current_open_positions, max_open_positions):
    """Return whether the account remains below its position-count limit."""
    return current_open_positions < max_open_positions


def calculate_available_csp_capital(
    total_capital,
    max_csp_capital_percent,
    current_csp_capital_committed,
):
    """Calculate uncommitted collateral under the configured CSP allocation."""
    max_csp_capital = total_capital * max_csp_capital_percent
    return max(0, max_csp_capital - current_csp_capital_committed)


def get_recommendation_results(
    current_open_positions=0,
    current_csp_capital_committed=0,
    external_available_csp_capital=None,
):
    """Scan approved tickers and return ranked candidates plus an AI review."""
    if not can_open_new_position(current_open_positions, MAX_OPEN_POSITIONS):
        return _rejection(f"Max open positions reached ({MAX_OPEN_POSITIONS}).", "Position limits prevent overcommitting the account.")

    available_capital = calculate_available_csp_capital(
        TOTAL_CAPITAL,
        MAX_CSP_CAPITAL_PERCENT,
        current_csp_capital_committed,
    )
    if external_available_csp_capital is not None:
        available_capital = min(available_capital, max(0, external_available_csp_capital))

    if available_capital <= 0:
        return _rejection("No CSP capital available under current allocation rules.", "Capital rules keep the account from being overcommitted.")

    try:
        latest_prices = get_latest_stock_prices(APPROVED_TICKERS)
    except Exception:
        latest_prices = {}

    candidate_frames = []
    for ticker_symbol in APPROVED_TICKERS:
        try:
            candidates = find_csp_candidates(
                ticker_symbol, MIN_DTE, MAX_DTE, TARGET_DELTA, DELTA_TOLERANCE,
                MAX_SPREAD, MIN_QUOTE_SIZE, MIN_IV_PERCENT, MAX_IV_PERCENT,
                MIN_ROC_PERCENT, available_capital,
                current_stock_price=latest_prices.get(ticker_symbol),
            )
        except Exception:
            continue

        if not candidates.empty:
            candidate_frames.append(candidates.head(CANDIDATES_PER_TICKER))

    if not candidate_frames:
        return _rejection("No CSP candidates found across approved tickers.", "The current filters may be too strict for today's market data.")

    combined = pd.concat(candidate_frames, ignore_index=True)
    top_candidates = combined.sort_values(by="score", ascending=False).head(MAX_RECOMMENDATIONS)
    review = review_csp_candidates("approved ticker list", top_candidates, STRATEGY_RULES)
    return {"candidates": top_candidates, "review": review}


def _rejection(summary, risk_note):
    """Build the common empty recommendation response."""
    return {
        "candidates": pd.DataFrame(),
        "review": {
            "decision": "reject_all",
            "selected_contract": None,
            "summary": summary,
            "risk_note": risk_note,
        },
    }
