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


## Fetch a saved recommendation run before a user acts on one of its contracts.
## Raising a clear validation error here keeps route handlers small and prevents unknown run ids from becoming confusing downstream failures.
def require_recommendation_run(run_id):
    run = get_recommendation_run(run_id)
    if run is None:
        raise ValueError("Recommendation run not found.")
    return run


## Confirm that a contract symbol belongs to the recommendation run the frontend referenced.
## This protects the paper-order path from accepting arbitrary contracts that were not shown to the user by HELIOS.
def require_candidate(run, contract_symbol):
    candidate = find_candidate(run, contract_symbol)
    if candidate is None:
        raise ValueError("Candidate not found in recommendation run.")
    return candidate


## Convert the candidate DataFrame into browser-safe JSON records.
## Pandas and NumPy values are normalized into plain Python types, and company names are attached so the UI can show ticker tooltips without extra API calls.
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


## Read Alpaca paper account balances while shielding routes from broker outages.
## If Alpaca is unavailable, the caller receives an explicit account_error instead of a crashed dashboard or recommendation response.
def get_safe_paper_account_summary():
    try:
        return get_paper_account_summary()
    except Exception as error:
        logger.warning("Paper account lookup failed: %s", type(error).__name__)
        return {"available_csp_cash": None, "account_error": "Paper account unavailable."}


## Read and normalize all current Alpaca paper positions.
## The returned error string lets the UI explain that live positions failed while still falling back to saved HELIOS memory where possible.
def get_safe_paper_positions():
    try:
        return get_paper_positions(), None
    except Exception as error:
        logger.warning("Paper position lookup failed: %s", type(error).__name__)
        return None, "Paper positions unavailable."


## Extract only open short-put positions from the full Alpaca portfolio.
## HELIOS uses this subset for CSP-specific capital limits because stock shares and other holdings should not count as cash-secured put slots.
def csp_positions_from_all_positions(positions):
    return [
        position for position in positions
        if position.get("strategy") == "cash-secured put"
    ]


## Separate stocks and non-CSP holdings for the portfolio display.
## Keeping them out of the CSP list avoids mixing regular holdings with option obligations.
def non_csp_positions_from_all_positions(positions):
    return [
        position for position in positions
        if position.get("strategy") != "cash-secured put"
    ]


## Choose the best available account value for strategy math.
## Live Alpaca portfolio value is preferred, but the prototype falls back to the configured paper capital when the broker omits account totals.
def account_total_capital(alpaca_account):
    return (
        (alpaca_account or {}).get("portfolio_value")
        or (alpaca_account or {}).get("equity")
        or TOTAL_CAPITAL
    )


## Sync recent Alpaca orders into HELIOS memory without blocking the dashboard.
## Order reconciliation is helpful for history, but a temporary Alpaca failure should not prevent users from seeing current positions.
def reconcile_orders_safely():
    try:
        return reconcile_paper_orders(get_paper_orders()), None
    except Exception as error:
        logger.warning("Paper order synchronization failed: %s", type(error).__name__)
        return 0, "Paper order synchronization unavailable."


## Compute the actual cash ceiling for a new CSP recommendation.
## HELIOS uses the stricter of strategy allocation and Alpaca options buying power so candidates shown to the user are realistically placeable.
def get_effective_available_csp_cash(capital_summary, alpaca_account):
    alpaca_available = (alpaca_account or {}).get("available_csp_cash")
    if alpaca_available is None:
        return capital_summary["available_csp_capital"]
    return min(capital_summary["available_csp_capital"], alpaca_available)


## Add live broker buying-power context to the local capital summary.
## The frontend displays both strategy capacity and effective CSP cash so users can see why a trade may be filtered out.
def attach_alpaca_cash_context(capital_summary, alpaca_account):
    capital_summary["alpaca_available_csp_cash"] = (alpaca_account or {}).get("available_csp_cash")
    capital_summary["effective_available_csp_capital"] = get_effective_available_csp_cash(
        capital_summary,
        alpaca_account,
    )
    return capital_summary


## Build a compact dashboard context for memory records and prompts.
## Full dashboard payloads contain repeated position arrays, so memory snapshots store only the account and capital fields needed to explain risk.
def compact_dashboard_memory_context(dashboard, trigger=None):
    capital = dict((dashboard or {}).get("capital") or {})
    capital.pop("open_positions", None)
    account = dict((dashboard or {}).get("account") or {})
    account = {
        key: account.get(key)
        for key in [
            "cash", "buying_power", "options_buying_power", "available_csp_cash",
            "portfolio_value", "equity", "long_market_value", "short_market_value",
        ]
        if key in account
    }

    return {
        "trigger": trigger,
        "position_source": (dashboard or {}).get("position_source"),
        "capital": capital,
        "account": account,
    }


## Build the Capital & Positions payload shown in the frontend dashboard.
## This combines saved HELIOS memory, reconciled orders, live Alpaca positions, and current buying power into one response for the UI.
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
