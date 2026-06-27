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

try:
    from backend.memory.dynamodb_store import USER_PK, get_item, put_item, utc_now_text
except ImportError:
    USER_PK = None
    get_item = None
    put_item = None
    utc_now_text = None

logger = logging.getLogger(__name__)


## Create a pending market-take job record and return its public status.
def create_market_take_job():
    if not put_item:
        raise RuntimeError("Async AI jobs require DynamoDB memory backend.")

    job_id = str(uuid4())
    now = utc_now_text()
    item = {
        "pk": USER_PK,
        "sk": f"AI_TAKE_JOB#{job_id}",
        "item_type": "ai_take_job",
        "job_id": job_id,
        "status": "pending",
        "created_at": now,
        "updated_at": now,
        "completed_at": None,
        "result": None,
        "error": None,
    }
    put_item(item)
    return _public_job(item)


## Return one market-take job by id.
def get_market_take_job(job_id):
    if not get_item:
        raise RuntimeError("Async AI jobs require DynamoDB memory backend.")
    item = get_item(USER_PK, f"AI_TAKE_JOB#{job_id}")
    return _public_job(item) if item else None


## Run the expensive market-take work and persist its final status.
def run_market_take_job(job_id):
    item = get_item(USER_PK, f"AI_TAKE_JOB#{job_id}")
    if not item:
        logger.warning("AI market take job not found: %s", job_id)
        return {"ok": False, "error": "job_not_found"}

    _update_job(item, status="running")
    try:
        context = build_market_context(APPROVED_TICKERS)
        dashboard = get_dashboard_with_cash_context()
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


## Persist job status changes while preserving creation metadata.
def _update_job(item, **changes):
    updated = {**item, **changes, "updated_at": utc_now_text()}
    put_item(updated)
    return updated


## Hide internal DynamoDB keys from API responses.
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
