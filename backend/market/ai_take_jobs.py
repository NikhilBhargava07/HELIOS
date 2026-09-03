## Run user-scoped AI Market Take jobs outside API Gateway's request timeout.
##
## The browser creates a short-lived DynamoDB job, Lambda performs the slower
## OpenAI request asynchronously, and the browser polls until a result is ready.

import logging

from backend.api.services import get_dashboard_with_cash_context
from backend.broker.clients import create_stock_data_client
from backend.broker.trading import create_trading_client
from backend.config import (
    APPROVED_TICKERS,
    COMPANY_NAMES,
)
from backend.market.ai_take import ai_market_take
from backend.market.context import build_market_context
from backend.memory.dynamodb_store import utc_now_text
from backend.memory.jobs import (
    create_job,
    public_job,
    read_job_item,
    update_job,
)
from backend.memory.recommendations import get_latest_recommendation_run
from backend.users.profiles import get_user_broker_credentials

logger = logging.getLogger(__name__)


JOB_SORT_KEY_PREFIX = "AI_TAKE_JOB"


## Create a pending AI market-take job inside the authenticated user's partition.
## The epoch expiration supports DynamoDB TTL cleanup once expires_at is enabled on the table.
def create_market_take_job(user_id):
    return create_job(user_id, JOB_SORT_KEY_PREFIX, "ai_take_job")


## Fetch one job only from the requesting user's private partition.
## A job id from another account therefore behaves exactly like a missing job.
def get_market_take_job(job_id, user_id):
    item = read_job_item(user_id, JOB_SORT_KEY_PREFIX, job_id)
    return public_job(item) if item else None


## Execute one background market-take job for its authenticated owner.
## Credentials are loaded once, then used to construct both broker clients needed by the evidence workflow.
def run_market_take_job(job_id, user_id):
    item = read_job_item(user_id, JOB_SORT_KEY_PREFIX, job_id)
    if not item:
        logger.warning("AI market take job not found: %s", job_id)
        return {"ok": False, "error": "job_not_found"}

    update_job(item, status="running")
    try:
        credentials = get_user_broker_credentials(user_id)
        if not credentials or credentials.get("broker") != "alpaca":
            raise RuntimeError(
                "Saved Alpaca connection is required for AI market take jobs."
            )

        trading_client = create_trading_client(
            credentials["api_key"],
            credentials["secret_key"],
        )
        stock_data_client = create_stock_data_client(
            credentials["api_key"],
            credentials["secret_key"],
        )
        context = build_market_context(
            APPROVED_TICKERS,
            stock_data_client=stock_data_client,
        )
        dashboard = get_dashboard_with_cash_context(
            user_id,
            trading_client=trading_client,
        )
        context["portfolio"] = {
            "open_csp_positions": dashboard["open_positions"],
            "capital": dashboard["capital"],
            "position_source": dashboard["position_source"],
        }
        context["latest_recommendation"] = get_latest_recommendation_run(
            user_id
        )
        result = ai_market_take(context)
        result["company_names"] = COMPANY_NAMES
        update_job(
            item,
            status="complete",
            result=result,
            error=None,
            completed_at=utc_now_text(),
        )
        return {"ok": True, "job_id": job_id}
    except Exception as error:
        logger.exception(
            "AI market take job failed: %s (%s)",
            job_id,
            type(error).__name__,
        )
        update_job(
            item,
            status="failed",
            error={
                "code": "market_take_failed",
                "message": "Could not generate the AI market take. Please try again.",
            },
            completed_at=utc_now_text(),
        )
        return {
            "ok": False,
            "job_id": job_id,
            "error": "market_take_failed",
        }


