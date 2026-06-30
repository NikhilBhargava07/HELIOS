## Shared API orchestration for candidates, Alpaca state, and dashboard data.

import logging

from backend.broker.trading import (
    get_paper_account_summary,
    get_paper_orders,
    get_paper_positions,
)
from backend.config import (
    COMPANY_NAMES,
    MAX_CSP_CAPITAL_PERCENT,
    MAX_OPEN_POSITIONS,
    TOTAL_CAPITAL,
)
from backend.memory.capital_and_positions import get_dashboard_data
from backend.memory.recommendations import find_candidate, get_recommendation_run
from backend.memory.trades import reconcile_paper_orders


logger = logging.getLogger(__name__)


## Load a saved recommendation or raise a clear validation error.
def require_recommendation_run(run_id):
    run = get_recommendation_run(run_id)
    if run is None:
        raise ValueError("Recommendation run not found.")
    return run


## Verify that a contract belongs to a saved recommendation run.
def require_candidate(run, contract_symbol):
    candidate = find_candidate(run, contract_symbol)
    if candidate is None:
        raise ValueError("Candidate not found in recommendation run.")
    return candidate


## Convert ranked candidate DataFrame rows into JSON-ready records.
def candidates_to_records(candidates):
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


## Return Alpaca account data without allowing broker errors to crash a route.
def get_safe_paper_account_summary():
    try:
        return get_paper_account_summary()
    except Exception as error:
        logger.warning("Paper account lookup failed: %s", type(error).__name__)
        return {"available_csp_cash": None, "account_error": "Paper account unavailable."}


## Return normalized Alpaca positions plus any recoverable error.
def get_safe_paper_positions():
    try:
        return get_paper_positions(), None
    except Exception as error:
        logger.warning("Paper position lookup failed: %s", type(error).__name__)
        return None, "Paper positions unavailable."


## Return only short-put CSP positions from a full Alpaca position list.
def csp_positions_from_all_positions(positions):
    return [
        position for position in positions
        if position.get("strategy") == "cash-secured put"
    ]


## Return non-CSP stock/option positions for general portfolio display.
def non_csp_positions_from_all_positions(positions):
    return [
        position for position in positions
        if position.get("strategy") != "cash-secured put"
    ]


## Choose live Alpaca portfolio value when available, otherwise local prototype capital.
def account_total_capital(alpaca_account):
    return (
        (alpaca_account or {}).get("portfolio_value")
        or (alpaca_account or {}).get("equity")
        or TOTAL_CAPITAL
    )


## Synchronize saved order history without failing the dashboard route.
def reconcile_orders_safely():
    try:
        return reconcile_paper_orders(get_paper_orders()), None
    except Exception as error:
        logger.warning("Paper order synchronization failed: %s", type(error).__name__)
        return 0, "Paper order synchronization unavailable."


## Use the lower of strategy allocation and Alpaca options buying power.
def get_effective_available_csp_cash(capital_summary, alpaca_account):
    alpaca_available = (alpaca_account or {}).get("available_csp_cash")
    if alpaca_available is None:
        return capital_summary["available_csp_capital"]
    return min(capital_summary["available_csp_capital"], alpaca_available)


## Add broker and effective buying-power fields to a capital summary.
def attach_alpaca_cash_context(capital_summary, alpaca_account):
    capital_summary["alpaca_available_csp_cash"] = (alpaca_account or {}).get("available_csp_cash")
    capital_summary["effective_available_csp_capital"] = get_effective_available_csp_cash(
        capital_summary,
        alpaca_account,
    )
    return capital_summary


## Combine saved history with live Alpaca positions and buying power.
def get_dashboard_with_cash_context(alpaca_account=None):
    reconciled_orders, order_sync_error = reconcile_orders_safely()
    safe_account = alpaca_account or get_safe_paper_account_summary()
    live_total_capital = account_total_capital(safe_account)
    dashboard = get_dashboard_data(live_total_capital, MAX_CSP_CAPITAL_PERCENT, MAX_OPEN_POSITIONS)
    alpaca_positions, position_error = get_safe_paper_positions()

    if alpaca_positions is not None:
        csp_positions = csp_positions_from_all_positions(alpaca_positions)
        non_csp_positions = non_csp_positions_from_all_positions(alpaca_positions)
        committed = sum(position["cash_required"] for position in csp_positions)
        max_csp_capital = live_total_capital * MAX_CSP_CAPITAL_PERCENT
        dashboard["open_positions"] = csp_positions
        dashboard["stock_positions"] = non_csp_positions
        dashboard["all_positions"] = alpaca_positions
        dashboard["capital"].update({
            "total_capital": live_total_capital,
            "max_csp_capital": max_csp_capital,
            "open_positions": csp_positions,
            "committed_capital": committed,
            "available_csp_capital": max(0, max_csp_capital - committed),
            "open_position_count": len(csp_positions),
            "total_open_position_count": len(alpaca_positions),
        })
    else:
        dashboard["stock_positions"] = []
        dashboard["all_positions"] = dashboard.get("open_positions", [])

    dashboard["capital"] = attach_alpaca_cash_context(dashboard["capital"], safe_account)
    dashboard.update({
        "account": safe_account,
        "position_source": "alpaca" if alpaca_positions is not None else "dynamodb",
        "position_error": position_error,
        "reconciled_orders": reconciled_orders,
        "order_sync_error": order_sync_error,
        "company_names": COMPANY_NAMES,
    })
    return dashboard
