## Shared API orchestration for candidates, Alpaca state, and dashboard data.

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone

from fastapi import HTTPException

from backend.broker.clients import (
    create_option_data_client,
    create_stock_data_client,
)
from backend.broker.trading import (
    create_trading_client,
    get_paper_account_summary,
    get_paper_orders,
    get_paper_positions,
    parse_option_contract_symbol,
    refresh_candidate_option_quote,
)
from backend.config import (
    COMPANY_NAMES,
    MAX_RECOMMENDATION_AGE_SECONDS,
    MAX_CSP_CAPITAL_PERCENT,
    MAX_OPEN_POSITIONS,
    MAX_SPREAD,
    MIN_QUOTE_SIZE,
    TOTAL_CAPITAL,
)
from backend.memory.capital_and_positions import get_dashboard_data
from backend.memory.recommendations import find_candidate, get_recommendation_run
from backend.memory.trades import reconcile_paper_orders
from backend.users.auth import require_authenticated_user
from backend.users.profiles import get_user_broker_credentials


logger = logging.getLogger(__name__)

ACTIVE_ORDER_STATUSES = {
    "new",
    "accepted",
    "pending_new",
    "partially_filled",
    "held",
    "pending_replace",
    "pending_cancel",
}


## Invoke this same Lambda asynchronously to run a background job (recommendation scan, AI market take).
## InvocationType "Event" returns immediately, so API Gateway's request timeout never bounds the heavy work.
def enqueue_worker(worker_action, job_id, user_id):
    import boto3

    function_name = os.getenv("AWS_LAMBDA_FUNCTION_NAME")
    if not function_name:
        raise RuntimeError("AWS_LAMBDA_FUNCTION_NAME is required for background jobs.")

    boto3.client("lambda").invoke(
        FunctionName=function_name,
        InvocationType="Event",
        Payload=json.dumps({
            "worker_action": worker_action,
            "job_id": job_id,
            "user_id": user_id,
        }).encode("utf-8"),
    )


## Hold the authenticated user and all Alpaca clients created from one credential read.
## Request-scoped reuse avoids repeated DynamoDB secret lookups and guarantees that trading and market data use the same connected broker account.
@dataclass(frozen=True)
class BrokerContext:
    user: object
    trading_client: object
    stock_data_client: object
    option_data_client: object


## Load one user's broker credentials and construct all required Alpaca clients once per request.
## The context is cached on request.state so routes can ask for individual clients without repeating profile or credential reads.
def get_required_broker_context(request):
    existing = getattr(request.state, "broker_context", None)
    if existing is not None:
        return existing

    user = require_authenticated_user(request)
    try:
        credentials = get_user_broker_credentials(user.user_id)
    except Exception as error:
        logger.warning("User broker credential lookup failed: %s", type(error).__name__)
        raise HTTPException(
            503,
            "Could not load your saved broker connection. Reconnect Alpaca from Profile.",
        ) from error

    if not credentials:
        raise HTTPException(
            428,
            "Connect Alpaca from the signup/profile page before using broker features.",
        )
    if credentials.get("broker") != "alpaca":
        raise HTTPException(400, "The saved brokerage is not supported.")

    try:
        context = BrokerContext(
            user=user,
            trading_client=create_trading_client(
                credentials["api_key"],
                credentials["secret_key"],
            ),
            stock_data_client=create_stock_data_client(
                credentials["api_key"],
                credentials["secret_key"],
            ),
            option_data_client=create_option_data_client(
                credentials["api_key"],
                credentials["secret_key"],
            ),
        )
    except Exception as error:
        logger.warning("User broker client creation failed: %s", type(error).__name__)
        raise HTTPException(
            503,
            "Could not initialize your saved broker connection. Reconnect Alpaca from Profile.",
        ) from error

    request.state.broker_context = context
    return context


## Build the signed-in user's Alpaca stock and option data clients.
## Market-data scans use this explicit path instead of APCA/ALPACA env keys, keeping recommendations tied to the user's connected broker account.
def get_required_user_market_data_clients(request):
    context = get_required_broker_context(request)
    return context.stock_data_client, context.option_data_client


## Fetch a saved recommendation run before a user acts on one of its contracts.
## Raising a clear validation error here keeps route handlers small and prevents unknown run ids from becoming confusing downstream failures.
def require_recommendation_run(user_id, run_id):
    run = get_recommendation_run(user_id, run_id)
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


## Reject a recommendation after its scan evidence has aged past the placement window.
## Option greeks and market context can move quickly, so an old card must be rescanned even though its exact quote is also refreshed.
def require_fresh_recommendation(run, maximum_age_seconds=MAX_RECOMMENDATION_AGE_SECONDS):
    created_at = run.get("created_at")
    if not created_at:
        raise ValueError("Recommendation timestamp is missing. Run a new CSP scan.")
    try:
        created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except (TypeError, ValueError) as error:
        raise ValueError("Recommendation timestamp is invalid. Run a new CSP scan.") from error
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    age_seconds = (datetime.now(timezone.utc) - created).total_seconds()
    if age_seconds > maximum_age_seconds:
        raise ValueError("This recommendation is stale. Run a new CSP scan before placing it.")


## Identify an unfilled sell-to-open put order that still has broker-side obligations.
## Pending CSP orders count toward the position cap because they can become positions without another user action.
def is_active_csp_order(order):
    contract = parse_option_contract_symbol(order.get("symbol"))
    side = str(order.get("side") or "").lower()
    status = str(order.get("status") or "").lower()
    return (
        side == "sell"
        and contract is not None
        and contract["option_type"] == "put"
        and status in ACTIVE_ORDER_STATUSES
    )


## Validate current broker and strategy limits, then refresh the selected option quote.
## This is the final server-side gate before a CSP paper order reaches Alpaca.
def prepare_candidate_for_paper_order(
    run,
    candidate,
    client_order_id,
    trading_client,
    option_data_client,
):
    broker_orders = get_paper_orders(limit=100, trading_client=trading_client)
    existing_order = next(
        (
            order
            for order in broker_orders
            if order.get("client_order_id") == client_order_id
        ),
        None,
    )
    if existing_order:
        return {
            "candidate": candidate,
            "account": None,
            "existing_order": existing_order,
        }

    require_fresh_recommendation(run)
    account = get_paper_account_summary(trading_client=trading_client)
    all_positions = get_paper_positions(trading_client=trading_client)
    csp_positions = csp_positions_from_all_positions(all_positions)
    active_csp_orders = [
        order for order in broker_orders
        if is_active_csp_order(order)
    ]
    contract_symbol = candidate["contractSymbol"]
    if any(
        position.get("contract_symbol") == contract_symbol
        for position in csp_positions
    ):
        raise ValueError("This CSP contract is already an open position.")
    if any(order.get("symbol") == contract_symbol for order in active_csp_orders):
        raise ValueError("An active Alpaca order already exists for this CSP contract.")
    if len(csp_positions) + len(active_csp_orders) >= MAX_OPEN_POSITIONS:
        raise ValueError(
            f"The {MAX_OPEN_POSITIONS}-position CSP limit includes pending orders and has been reached."
        )

    total_capital = account_total_capital(account)
    committed = sum(float(position.get("cash_required") or 0) for position in csp_positions)
    strategy_available = max(
        0,
        total_capital * MAX_CSP_CAPITAL_PERCENT - committed,
    )
    broker_available = account.get("available_csp_cash")
    if broker_available is None:
        raise ValueError("Alpaca did not report options buying power, so HELIOS cannot verify this CSP safely.")
    available_cash = min(strategy_available, broker_available)
    cash_required = float(candidate.get("cashRequired") or 0)
    if cash_required > available_cash:
        raise ValueError(
            f"This CSP requires ${cash_required:,.2f}, but current strategy and broker limits allow ${available_cash:,.2f}."
        )

    refreshed_candidate = refresh_candidate_option_quote(
        candidate,
        option_data_client,
        MAX_SPREAD,
        MIN_QUOTE_SIZE,
    )
    return {
        "candidate": refreshed_candidate,
        "account": account,
        "existing_order": None,
    }


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
def get_safe_paper_account_summary(trading_client=None):
    try:
        return get_paper_account_summary(trading_client=trading_client)
    except Exception as error:
        logger.warning("Paper account lookup failed: %s", type(error).__name__)
        return {"available_csp_cash": None, "account_error": "Paper account unavailable."}


## Read and normalize all current Alpaca paper positions.
## The returned error string lets the UI explain that live positions failed while still falling back to saved HELIOS memory where possible.
def get_safe_paper_positions(trading_client=None):
    try:
        return get_paper_positions(trading_client=trading_client), None
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
def reconcile_orders_safely(user_id, trading_client=None, broker_orders=None):
    try:
        return reconcile_paper_orders(
            user_id,
            (
                broker_orders
                if broker_orders is not None
                else get_paper_orders(limit=100, trading_client=trading_client)
            ),
        ), None
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
    enriched = dict(capital_summary)
    enriched["alpaca_available_csp_cash"] = (alpaca_account or {}).get("available_csp_cash")
    enriched["effective_available_csp_capital"] = get_effective_available_csp_cash(
        enriched,
        alpaca_account,
    )
    return enriched


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
def get_dashboard_with_cash_context(
    user_id,
    alpaca_account=None,
    trading_client=None,
    broker_orders=None,
):
    reconciled_orders, order_sync_error = reconcile_orders_safely(
        user_id,
        trading_client=trading_client,
        broker_orders=broker_orders,
    )
    safe_account = alpaca_account or get_safe_paper_account_summary(trading_client=trading_client)
    live_total_capital = account_total_capital(safe_account)
    dashboard = get_dashboard_data(
        user_id,
        live_total_capital,
        MAX_CSP_CAPITAL_PERCENT,
        MAX_OPEN_POSITIONS,
    )
    alpaca_positions, position_error = get_safe_paper_positions(trading_client=trading_client)

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
