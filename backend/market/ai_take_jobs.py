## Async AI Market Take job orchestration for Lambda deployment.
##
## API Gateway has a short request timeout, so the frontend creates a job and
## polls DynamoDB while a separate asynchronous Lambda invocation calls OpenAI.

import logging
import traceback
from uuid import uuid4

from backend.api.services import get_dashboard_with_cash_context
from backend.config import APPROVED_TICKERS, COMPANY_NAMES
from backend.market.ai_take import ai_market_take
from backend.market.context import build_market_context
from backend.memory.recommendations import get_latest_recommendation_run
from backend.users.profiles import get_user_market_data_clients, get_user_trading_client

try:
    from backend.memory.dynamodb_store import USER_PK, get_item, put_item, utc_now_text
except ImportError:
    USER_PK = None
    get_item = None
    put_item = None
    utc_now_text = None

logger = logging.getLogger(__name__)


## Create a pending AI market-take job record in DynamoDB.
## The returned job id lets the browser poll while Lambda finishes the longer OpenAI call in the background.
def create_market_take_job(user_id):
    if not put_item:
        raise RuntimeError("Async AI jobs require DynamoDB memory backend.")

    job_id = str(uuid4())
    now = utc_now_text()
    item = {
        "pk": USER_PK,
        "sk": f"AI_TAKE_JOB#{job_id}",
        "item_type": "ai_take_job",
        "job_id": job_id,
        "user_id": user_id,
        "status": "pending",
        "created_at": now,
        "updated_at": now,
        "completed_at": None,
        "result": None,
        "error": None,
    }
    put_item(item)
    return _public_job(item)


## Fetch one market-take job and return only public fields.
## This hides storage details while giving the UI status, result, or error information.
def get_market_take_job(job_id, user_id=None):
    if not get_item:
        raise RuntimeError("Async AI jobs require DynamoDB memory backend.")
    item = get_item(USER_PK, f"AI_TAKE_JOB#{job_id}")
    if not item:
        return None
    if user_id is not None and item.get("user_id") != user_id:
        return None
    return _public_job(item)


## Execute the background AI market-take workflow for one job id.
## Lambda invokes this internally after the API route creates the job record.
def run_market_take_job(job_id):
    item = get_item(USER_PK, f"AI_TAKE_JOB#{job_id}")
    if not item:
        logger.warning("AI market take job not found: %s", job_id)
        return {"ok": False, "error": "job_not_found"}

    _update_job(item, status="running")
    try:
        user_id = item.get("user_id")
        trading_client = get_user_trading_client(user_id) if user_id else None
        stock_data_client, _ = get_user_market_data_clients(user_id) if user_id else (None, None)
        if trading_client is None or stock_data_client is None:
            raise RuntimeError("Saved broker connection is required for AI market take jobs.")

        context = build_market_context(APPROVED_TICKERS, stock_data_client=stock_data_client)
        dashboard = get_dashboard_with_cash_context(trading_client=trading_client)
        context["portfolio"] = {
            "open_csp_positions": dashboard["open_positions"],
            "capital": dashboard["capital"],
            "position_source": dashboard["position_source"],
        }
        context["latest_recommendation"] = get_latest_recommendation_run()
        result = ai_market_take(context)
        result["company_names"] = COMPANY_NAMES
        _update_job(item, status="complete", result=result, completed_at=utc_now_text())
        return {"ok": True, "job_id": job_id}
    except Exception as error:
        logger.exception("AI market take job failed: %s", job_id)
        _update_job(
            item,
            status="failed",
            error={
                "type": type(error).__name__,
                "message": str(error),
                "trace": traceback.format_exc(limit=6),
            },
            completed_at=utc_now_text(),
        )
        return {"ok": False, "job_id": job_id, "error": type(error).__name__}


## Update a market-take job record with status, result, or error details.
## All job state changes go through one helper so DynamoDB writes remain consistent.
def _update_job(item, **changes):
    updated = {**item, **changes, "updated_at": utc_now_text()}
    put_item(updated)
    return updated


## Remove DynamoDB bookkeeping fields before returning a job to the frontend.
## The UI only needs the job id, status, result, and any user-facing error.
def _public_job(item):
    return {
        "job_id": item["job_id"],
        "status": item["status"],
        "created_at": item.get("created_at"),
        "updated_at": item.get("updated_at"),
        "completed_at": item.get("completed_at"),
        "result": item.get("result"),
        "error": item.get("error"),
    }
