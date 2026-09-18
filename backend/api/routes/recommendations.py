## Recommendation generation and user-decision HTTP routes.

import logging

from fastapi import APIRouter, HTTPException, Request

from backend.api.schemas import UserDecisionAction, UserDecisionRequest
from backend.api.services import (
    enqueue_worker,
    get_dashboard_with_cash_context,
    get_required_broker_context,
    prepare_candidate_for_paper_order,
    require_candidate,
    require_recommendation_run,
)
from backend.broker.trading import (
    build_helios_client_order_id,
    submit_cash_secured_put_order,
)
from backend.memory.trades import record_user_decision
from backend.strategy.registry import DEFAULT_STRATEGY_KEY, get_strategy
from backend.strategy.recommendation_jobs import (
    create_recommendation_job,
    get_recommendation_job,
)
from backend.users.auth import require_authenticated_user

router = APIRouter(prefix="/api", tags=["recommendations"])
logger = logging.getLogger(__name__)


@router.post("/recommendations/jobs")
## Start a background recommendation scan for one strategy and return its job id immediately.
## The multi-ticker scan runs in a Lambda worker, so it is not bounded by the API Gateway request timeout that made the synchronous scan fail at ~30 seconds.
## An unknown strategy is rejected before any job is created, so a typo cannot leave an orphaned job behind.
def start_recommendation_job(request: Request, strategy: str = DEFAULT_STRATEGY_KEY):
    try:
        scan_strategy = get_strategy(strategy)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    broker_context = get_required_broker_context(request)
    user_id = broker_context.user.user_id
    job = create_recommendation_job(user_id, scan_strategy.key)
    try:
        enqueue_worker("recommendation_scan", job["job_id"], user_id)
    except Exception as error:
        logger.exception(
            "Could not enqueue recommendation job %s: %s",
            job["job_id"],
            type(error).__name__,
        )
        raise HTTPException(
            status_code=503,
            detail=f"Could not start the {scan_strategy.short_label} scan. Please try again.",
        ) from error
    return job


@router.get("/recommendations/jobs/{job_id}")
## Return the latest status, and the full scan result once complete, for a recommendation job.
## This backs the polling loop that keeps the multi-ticker scan from freezing the UI.
def read_recommendation_job(job_id, request: Request):
    user = require_authenticated_user(request)
    job = get_recommendation_job(job_id, user.user_id)
    if not job:
        raise HTTPException(status_code=404, detail="Recommendation job not found.")
    return job


@router.post("/decisions")
## Record a user decision from the recommendation cards.
## Paper-place actions are submitted to Alpaca first, then the decision is stored in memory so later learning can compare recommendation versus user behavior.
def post_user_decision(request: UserDecisionRequest, http_request: Request):
    broker_context = get_required_broker_context(http_request)
    user_id = broker_context.user.user_id
    trading_client = broker_context.trading_client
    option_data_client = broker_context.option_data_client
    alpaca_order = None
    alpaca_account = None
    order_error = None
    store_action = request.action.value
    duplicate_prevented = False

    if request.action == UserDecisionAction.PLACE_PAPER_ORDER:
        try:
            run = require_recommendation_run(
                user_id,
                request.recommendation_run_id,
            )
            candidate = require_candidate(run, request.contract_symbol)
            client_order_id = build_helios_client_order_id(
                user_id,
                request.recommendation_run_id,
                request.contract_symbol,
            )
            placement = prepare_candidate_for_paper_order(
                run,
                candidate,
                client_order_id,
                trading_client,
                option_data_client,
            )
            candidate = placement["candidate"]
            alpaca_account = placement["account"]
            alpaca_order = placement["existing_order"]
            duplicate_prevented = alpaca_order is not None
            if alpaca_order is None:
                alpaca_order = submit_cash_secured_put_order(
                    candidate,
                    trading_client=trading_client,
                    client_order_id=client_order_id,
                )
        except Exception as error:
            store_action = "place_paper_order_failed"
            order_error = str(error)
            decision = record_user_decision(
                user_id,
                request.recommendation_run_id,
                request.contract_symbol,
                store_action, request.note, order_error=order_error,
            )
            return {
                "decision": decision, "order_submitted": False,
                "order_error": order_error, "refresh_recommendations": True,
                "dashboard": get_dashboard_with_cash_context(
                    user_id,
                    alpaca_account,
                    trading_client=trading_client,
                ),
            }

    decision = record_user_decision(
        user_id,
        request.recommendation_run_id,
        request.contract_symbol,
        store_action,
        request.note,
        alpaca_order=alpaca_order,
        order_error=order_error,
        candidate_override=(candidate if request.action == UserDecisionAction.PLACE_PAPER_ORDER else None),
    )
    return {
        "decision": decision,
        "order_submitted": alpaca_order is not None,
        "duplicate_prevented": duplicate_prevented,
        "alpaca_order": alpaca_order,
        "refresh_recommendations": request.action == UserDecisionAction.PLACE_PAPER_ORDER,
        "dashboard": get_dashboard_with_cash_context(
            user_id,
            trading_client=trading_client,
        ),
    }
