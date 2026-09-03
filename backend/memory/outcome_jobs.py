## Run broker-backed CSP lifecycle observations on demand or before a scan.
##
## The private prototype does not require a schedule: a user action invokes one
## asynchronous job for that account. The optional dispatcher remains available
## for a later production EventBridge schedule.

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
from backend.memory.dynamodb_store import utc_now_text
from backend.memory.jobs import (
    create_job,
    public_job,
    read_job_item,
    update_job,
)
from backend.memory.observations import capture_current_csp_outcome_snapshots
from backend.memory.outcome_review import analyze_unreviewed_outcomes
from backend.memory.outcomes import finalize_csp_trade_outcomes
from backend.memory.trades import (
    import_filled_csp_order_history,
    reconcile_paper_orders,
)
from backend.users.profiles import (
    get_user_broker_credentials,
    list_connected_broker_user_ids,
)

logger = logging.getLogger(__name__)


JOB_SORT_KEY_PREFIX = "OUTCOME_JOB"


## Create a pending learning refresh that the frontend can start without EventBridge.
## The record uses the existing AI-job TTL convention so old polling state can be removed automatically once table TTL is enabled.
def create_outcome_observation_job(user_id):
    return create_job(user_id, JOB_SORT_KEY_PREFIX, "outcome_observation_job")


## Return one learning refresh only from its authenticated owner's partition.
## A guessed job id from another user therefore behaves like a missing record.
def get_outcome_observation_job(job_id, user_id):
    item = read_job_item(user_id, JOB_SORT_KEY_PREFIX, job_id)
    return public_job(item) if item else None


## Observe one user's current CSPs and finalize any option legs with broker evidence.
## Callers may supply already-created clients and broker data so a recommendation scan can refresh learning without repeating every network lookup.
def run_outcome_observation(
    user_id,
    job_id=None,
    trigger="on_demand",
    include_market_context=True,
    trading_client=None,
    stock_data_client=None,
    account=None,
    positions=None,
    broker_orders=None,
    credentials=None,
):
    job_item = read_job_item(user_id, JOB_SORT_KEY_PREFIX, job_id) if job_id else None
    if job_id and not job_item:
        logger.warning("Outcome observation job not found: %s", job_id)
        return {"ok": False, "error": "job_not_found"}
    if job_item:
        update_job(job_item, status="running")

    try:
        result = _run_outcome_observation(
            user_id,
            trigger=trigger,
            include_market_context=include_market_context,
            trading_client=trading_client,
            stock_data_client=stock_data_client,
            account=account,
            positions=positions,
            broker_orders=broker_orders,
            credentials=credentials,
        )
    except Exception as error:
        logger.exception(
            "Outcome observation failed for user %s: %s",
            user_id,
            type(error).__name__,
        )
        if job_item:
            update_job(
                job_item,
                status="failed",
                error={
                    "code": "outcome_observation_failed",
                    "message": "Could not refresh trade learning. Please try again.",
                },
                completed_at=utc_now_text(),
            )
            return {
                "ok": False,
                "job_id": job_id,
                "error": "outcome_observation_failed",
            }
        raise

    if job_item:
        update_job(
            job_item,
            status="complete" if result.get("ok") else "failed",
            result=result if result.get("ok") else None,
            error=(
                None
                if result.get("ok")
                else {
                    "code": result.get("error", "outcome_observation_failed"),
                    "message": "A connected Alpaca paper account is required.",
                }
            ),
            completed_at=utc_now_text(),
        )
    return result


## Perform the broker-backed learning refresh independently of HTTP and job bookkeeping.
## The refresh imports factual CSP history, captures one daily snapshot, finalizes supported outcomes, and analyzes only outcomes that lack a saved review.
def _run_outcome_observation(
    user_id,
    trigger,
    include_market_context,
    trading_client,
    stock_data_client,
    account,
    positions,
    broker_orders,
    credentials,
):
    credentials = credentials or get_user_broker_credentials(user_id)
    if not credentials or credentials.get("broker") != "alpaca":
        return {"ok": False, "user_id": user_id, "error": "broker_not_connected"}

    trading_client = trading_client or create_trading_client(
        credentials["api_key"], credentials["secret_key"]
    )
    account = account or get_paper_account_summary(trading_client=trading_client)
    positions = (
        positions
        if positions is not None
        else get_paper_positions(trading_client=trading_client)
    )
    broker_orders = (
        broker_orders
        if broker_orders is not None
        else get_paper_orders(limit=500, trading_client=trading_client)
    )
    historical_import = import_filled_csp_order_history(user_id, broker_orders)
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
    if tickers and include_market_context and stock_data_client is None:
        stock_data_client = create_stock_data_client(
            credentials["api_key"], credentials["secret_key"]
        )
    market_context = (
        build_candidate_review_context(
            tickers,
            stock_data_client=stock_data_client,
        )
        if tickers and include_market_context
        else {}
    )
    observation_context = {
        "trigger": trigger,
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
    reviewed_outcomes = analyze_unreviewed_outcomes(user_id, limit=5)
    return {
        "ok": True,
        "user_id": user_id,
        "historical_orders_imported": historical_import["imported"],
        "ambiguous_put_sales_skipped": historical_import[
            "skipped_ambiguous_put_sales"
        ],
        "snapshots_captured": snapshots["captured"],
        "outcomes_completed": finalization["completed"],
        "outcomes_reviewed": len(reviewed_outcomes),
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
