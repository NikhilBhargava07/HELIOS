## On-demand outcome learning and explicit trade-feedback HTTP routes.
##
## These endpoints replace a mandatory scheduled refresh during the private
## prototype. Work runs only when the user asks for it or starts a new CSP scan,
## so EventBridge can remain disabled until production monitoring is desired.

import logging

from fastapi import APIRouter, HTTPException, Request

from backend.api.schemas import TradeFeedbackRequest
from backend.api.services import enqueue_worker, get_required_broker_context
from backend.memory.feedback import get_trade_feedback, save_trade_feedback
from backend.memory.learning_user import build_user_profile, get_outcome_patterns
from backend.memory.outcome_jobs import (
    create_outcome_observation_job,
    get_outcome_observation_job,
)
from backend.memory.outcomes import get_completed_trade_outcomes
from backend.users.auth import require_authenticated_user


router = APIRouter(prefix="/api/learning", tags=["learning"])
logger = logging.getLogger(__name__)


## Remove storage keys, broker evidence ids, and oversized raw contexts from one outcome response.
## The learning page receives the economics and saved lesson it needs without exposing internal DynamoDB structure.
def _public_outcome(outcome):
    return {
        key: outcome.get(key)
        for key in (
            "completed_at",
            "opening_order_id",
            "opening_source",
            "recommendation_run_id",
            "contract_symbol",
            "ticker_symbol",
            "resolution_type",
            "assigned",
            "quantity",
            "strike",
            "expiration",
            "opening_credit",
            "closing_debit",
            "option_realized_pnl",
            "premium_retained_percent",
            "assignment_cash_obligation",
            "effective_share_cost",
            "underlying_outcome_pending",
            "entry_factors",
            "interpretation",
            "outcome_review",
        )
    }


@router.post("/jobs")
## Start an asynchronous broker-history and outcome refresh for the signed-in user.
## The API responds immediately and the browser can poll the job, avoiding API Gateway's request timeout without requiring EventBridge.
def start_learning_refresh(request: Request):
    broker_context = get_required_broker_context(request)
    user_id = broker_context.user.user_id
    job = create_outcome_observation_job(user_id)
    try:
        enqueue_worker("outcome_observation", job["job_id"], user_id)
    except Exception as error:
        logger.exception(
            "Could not enqueue learning refresh %s: %s",
            job["job_id"],
            type(error).__name__,
        )
        raise HTTPException(
            status_code=503,
            detail="Could not start the learning refresh. Please try again.",
        ) from error
    return job


@router.get("/jobs/{job_id}")
## Return the latest status and result for one owner-scoped learning refresh.
## Completed results report imports, snapshots, finalized outcomes, and generated reviews without exposing raw broker credentials.
def read_learning_refresh(job_id, request: Request):
    user = require_authenticated_user(request)
    job = get_outcome_observation_job(job_id, user.user_id)
    if not job:
        raise HTTPException(status_code=404, detail="Learning refresh job not found.")
    return job


@router.get("")
## Return the current learned profile, outcome evidence, and explicit feedback.
## This read-only summary can back a future Profile or Learning UI and never triggers broker or OpenAI charges by itself.
def get_learning_summary(request: Request):
    user = require_authenticated_user(request)
    outcomes = get_completed_trade_outcomes(user.user_id, limit=50)
    return {
        "user_profile": build_user_profile(user.user_id),
        "outcome_patterns": get_outcome_patterns(user.user_id),
        "completed_outcomes": [_public_outcome(outcome) for outcome in outcomes],
        "trade_feedback": get_trade_feedback(user.user_id, limit=50),
        "refresh_mode": "on_demand_and_before_recommendations",
        "scheduled_refresh_enabled": False,
    }


@router.post("/feedback")
## Save the user's interpretation of one paper trade independently from financial performance.
## Reposting feedback for the same order replaces the prior response, allowing the user to revise their view as an assignment develops.
def post_trade_feedback(payload: TradeFeedbackRequest, request: Request):
    user = require_authenticated_user(request)
    try:
        feedback = save_trade_feedback(
            user.user_id,
            payload.opening_order_id,
            payload.satisfaction.value,
            payload.would_repeat,
            payload.assignment_preference.value,
            [reason.value for reason in payload.reason_tags],
            payload.note,
        )
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return {
        "saved": True,
        "feedback": feedback,
        "user_profile": build_user_profile(user.user_id),
    }
