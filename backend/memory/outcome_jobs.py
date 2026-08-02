## Run and dispatch broker-backed CSP lifecycle observations.
##
## EventBridge invokes one lightweight dispatcher. The dispatcher asynchronously
## invokes this Lambda once per connected user, keeping broker credentials and
## failures isolated while avoiding API Gateway's request timeout.

import json
import logging
import os
from datetime import datetime, timedelta, timezone

from backend.broker.clients import create_stock_data_client
from backend.broker.trading import (
    create_trading_client,
    get_option_lifecycle_activities,
    get_paper_account_summary,
    get_paper_orders,
    get_paper_positions,
)
from backend.market.context import build_candidate_review_context
from backend.memory.observations import capture_current_csp_outcome_snapshots
from backend.memory.outcomes import finalize_csp_trade_outcomes
from backend.memory.trades import reconcile_paper_orders
from backend.users.profiles import (
    get_user_broker_credentials,
    list_connected_broker_user_ids,
)

logger = logging.getLogger(__name__)


## Observe one user's current CSPs and finalize any option legs with broker evidence.
## The job records daily live-position snapshots first, then uses filled closing orders or Alpaca lifecycle activities to complete outcomes.
def run_outcome_observation(user_id):
    credentials = get_user_broker_credentials(user_id)
    if not credentials or credentials.get("broker") != "alpaca":
        return {"ok": False, "user_id": user_id, "error": "broker_not_connected"}

    trading_client = create_trading_client(
        credentials["api_key"],
        credentials["secret_key"],
    )
    account = get_paper_account_summary(trading_client=trading_client)
    positions = get_paper_positions(trading_client=trading_client)
    broker_orders = get_paper_orders(limit=500, trading_client=trading_client)
    reconcile_paper_orders(user_id, broker_orders)

    csp_positions = [
        position
        for position in positions
        if position.get("strategy") == "cash-secured put"
    ]
    tickers = list(dict.fromkeys(
        position.get("ticker_symbol")
        for position in csp_positions
        if position.get("ticker_symbol")
    ))
    stock_data_client = (
        create_stock_data_client(
            credentials["api_key"],
            credentials["secret_key"],
        )
        if tickers
        else None
    )
    market_context = (
        build_candidate_review_context(
            tickers,
            stock_data_client=stock_data_client,
        )
        if tickers
        else {}
    )
    observation_context = {
        "trigger": "scheduled_outcome_observation",
        "capital": {
            "total_capital": account.get("portfolio_value"),
            "effective_available_csp_capital": account.get("available_csp_cash"),
            "open_position_count": len(csp_positions),
        },
        "market_context": market_context,
    }
    snapshots = capture_current_csp_outcome_snapshots(
        user_id,
        csp_positions,
        context=observation_context,
    )

    activity_after = (
        datetime.now(timezone.utc) - timedelta(days=120)
    ).date().isoformat()
    activity_error = None
    try:
        activities = get_option_lifecycle_activities(
            after=activity_after,
            trading_client=trading_client,
        )
    except Exception as error:
        logger.warning(
            "Option lifecycle activity lookup failed for user %s: %s",
            user_id,
            type(error).__name__,
        )
        activities = []
        activity_error = "option_lifecycle_activities_unavailable"

    finalization = finalize_csp_trade_outcomes(
        user_id,
        positions,
        broker_orders,
        activities,
    )
    return {
        "ok": True,
        "user_id": user_id,
        "snapshots_captured": snapshots["captured"],
        "outcomes_completed": finalization["completed"],
        "unresolved_count": len(finalization["unresolved"]),
        "activity_error": activity_error,
    }


## Fan out one asynchronous outcome-observation invocation per connected user.
## Per-user workers keep a slow or unavailable broker account from blocking observations for every other HELIOS account.
def dispatch_scheduled_outcome_observations():
    import boto3

    function_name = os.getenv("AWS_LAMBDA_FUNCTION_NAME")
    if not function_name:
        raise RuntimeError("AWS_LAMBDA_FUNCTION_NAME is required for scheduled observations.")

    lambda_client = boto3.client("lambda")
    user_ids = list_connected_broker_user_ids()
    failed_user_ids = []
    for user_id in user_ids:
        try:
            lambda_client.invoke(
                FunctionName=function_name,
                InvocationType="Event",
                Payload=json.dumps({
                    "worker_action": "outcome_observation",
                    "user_id": user_id,
                }).encode("utf-8"),
            )
        except Exception:
            logger.exception(
                "Could not dispatch outcome observation for user %s",
                user_id,
            )
            failed_user_ids.append(user_id)
    return {
        "ok": not failed_user_ids,
        "users_dispatched": len(user_ids) - len(failed_user_ids),
        "users_failed": len(failed_user_ids),
    }
