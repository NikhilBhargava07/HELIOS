"""Shared API orchestration for candidates, Alpaca state, and dashboard data."""

import logging

from backend.broker.trading import (
    get_paper_account_summary,
    get_paper_csp_positions,
    get_paper_orders,
)
from backend.config import (
    COMPANY_NAMES,
    MAX_CSP_CAPITAL_PERCENT,
    MAX_OPEN_POSITIONS,
    TOTAL_CAPITAL,
)
from backend.memory.dashboard import get_dashboard_data
from backend.memory.recommendations import find_candidate, get_recommendation_run
from backend.memory.trades import reconcile_paper_orders


logger = logging.getLogger(__name__)


def require_recommendation_run(run_id):
    """Load a saved recommendation or raise a clear validation error."""
    run = get_recommendation_run(run_id)
    if run is None:
        raise ValueError("Recommendation run not found.")
    return run


def require_candidate(run, contract_symbol):
    """Verify that a contract belongs to a saved recommendation run."""
    candidate = find_candidate(run, contract_symbol)
    if candidate is None:
        raise ValueError("Candidate not found in recommendation run.")
    return candidate


def candidates_to_records(candidates):
    """Convert ranked candidate DataFrame rows into JSON-ready records."""
    if candidates.empty:
        return []
    columns = [
        "tickerSymbol", "contractSymbol", "expiration", "DTE", "strike",
        "currentStockPrice", "delta", "ivPercent", "spread",
        "premiumIfSoldAtBid", "cashRequired", "breakevenPrice",
        "returnOnCashPercent",
    ]
    records = candidates[columns].to_dict(orient="records")
    for record in records:
        for key, value in record.items():
            if hasattr(value, "item"):
                record[key] = value.item()
        record["companyName"] = COMPANY_NAMES.get(record["tickerSymbol"], record["tickerSymbol"])
    return records


def get_safe_paper_account_summary():
    """Return Alpaca account data without allowing broker errors to crash a route."""
    try:
        return get_paper_account_summary()
    except Exception as error:
        logger.warning("Paper account lookup failed: %s", type(error).__name__)
        return {"available_csp_cash": None, "account_error": "Paper account unavailable."}


def get_safe_paper_csp_positions():
    """Return normalized Alpaca CSP positions plus any recoverable error."""
    try:
        return get_paper_csp_positions(), None
    except Exception as error:
        logger.warning("Paper position lookup failed: %s", type(error).__name__)
        return None, "Paper positions unavailable."


def reconcile_orders_safely():
    """Synchronize Postgres order history without failing the dashboard route."""
    try:
        return reconcile_paper_orders(get_paper_orders()), None
    except Exception as error:
        logger.warning("Paper order synchronization failed: %s", type(error).__name__)
        return 0, "Paper order synchronization unavailable."


def get_effective_available_csp_cash(capital_summary, alpaca_account):
    """Use the lower of strategy allocation and Alpaca options buying power."""
    alpaca_available = (alpaca_account or {}).get("available_csp_cash")
    if alpaca_available is None:
        return capital_summary["available_csp_capital"]
    return min(capital_summary["available_csp_capital"], alpaca_available)


def attach_alpaca_cash_context(capital_summary, alpaca_account):
    """Add broker and effective buying-power fields to a capital summary."""
    capital_summary["alpaca_available_csp_cash"] = (alpaca_account or {}).get("available_csp_cash")
    capital_summary["effective_available_csp_capital"] = get_effective_available_csp_cash(
        capital_summary,
        alpaca_account,
    )
    return capital_summary


def get_dashboard_with_cash_context(alpaca_account=None):
    """Combine Postgres history with live Alpaca positions and buying power."""
    reconciled_orders, order_sync_error = reconcile_orders_safely()
    dashboard = get_dashboard_data(TOTAL_CAPITAL, MAX_CSP_CAPITAL_PERCENT, MAX_OPEN_POSITIONS)
    safe_account = alpaca_account or get_safe_paper_account_summary()
    alpaca_positions, position_error = get_safe_paper_csp_positions()

    if alpaca_positions is not None:
        committed = sum(position["cash_required"] for position in alpaca_positions)
        dashboard["open_positions"] = alpaca_positions
        dashboard["capital"].update({
            "open_positions": alpaca_positions,
            "committed_capital": committed,
            "available_csp_capital": max(0, dashboard["capital"]["max_csp_capital"] - committed),
            "open_position_count": len(alpaca_positions),
        })

    dashboard["capital"] = attach_alpaca_cash_context(dashboard["capital"], safe_account)
    dashboard.update({
        "position_source": "alpaca" if alpaca_positions is not None else "postgres",
        "position_error": position_error,
        "reconciled_orders": reconciled_orders,
        "order_sync_error": order_sync_error,
        "company_names": COMPANY_NAMES,
    })
    return dashboard
