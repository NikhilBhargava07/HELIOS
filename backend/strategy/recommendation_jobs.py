## Run user-scoped CSP recommendation scans outside API Gateway's request timeout.
##
## The multi-ticker option scan plus AI review can exceed API Gateway's 30-second
## limit, so the browser creates a short-lived DynamoDB job, Lambda performs the
## scan asynchronously, and the browser polls until the result is ready. This is
## the same pattern the AI market-take feature already uses.

import logging
import time
from uuid import uuid4

from backend.api.services import (
    attach_alpaca_cash_context,
    candidates_to_records,
    compact_dashboard_memory_context,
    get_dashboard_with_cash_context,
    get_effective_available_csp_cash,
    get_safe_paper_account_summary,
)
from backend.broker.clients import (
    create_option_data_client,
    create_stock_data_client,
)
from backend.broker.trading import create_trading_client
from backend.config import (
    AI_JOB_TTL_SECONDS,
    APPROVED_TICKERS,
    COMPANY_NAMES,
    STRATEGY_RULES,
)
from backend.memory.dynamodb_store import (
    get_item,
    put_item,
    user_pk,
    utc_now_text,
)
from backend.memory.observations import capture_current_csp_outcome_snapshots
from backend.memory.recommendations import save_recommendation_run
from backend.strategy.recommender import get_recommendation_results
from backend.users.profiles import get_user_broker_credentials

logger = logging.getLogger(__name__)


## Build the sort key shared by all reads and writes for one recommendation job.
## Keeping this format in one helper prevents route and worker code from drifting apart.
def _job_sk(job_id):
    return f"RECOMMENDATION_JOB#{job_id}"


## Create a pending recommendation-scan job inside the authenticated user's partition.
## The epoch expiration supports DynamoDB TTL cleanup once expires_at is enabled on the table.
def create_recommendation_job(user_id):
    job_id = str(uuid4())
    now = utc_now_text()
    item = {
        "pk": user_pk(user_id),
        "sk": _job_sk(job_id),
        "item_type": "recommendation_job",
        "job_id": job_id,
        "user_id": user_id,
        "status": "pending",
        "created_at": now,
        "updated_at": now,
        "completed_at": None,
        "expires_at": int(time.time()) + AI_JOB_TTL_SECONDS,
        "result": None,
        "error": None,
    }
    put_item(item)
    return _public_job(item)


## Fetch one job only from the requesting user's private partition.
## A job id from another account therefore behaves exactly like a missing job.
def get_recommendation_job(job_id, user_id):
    item = get_item(user_pk(user_id), _job_sk(job_id))
    return _public_job(item) if item else None


## Execute one background CSP scan for its owner and store the full response payload.
## Credentials are loaded once, then used to build the trading and market-data clients the scan needs.
def run_recommendation_job(job_id, user_id):
    item = get_item(user_pk(user_id), _job_sk(job_id))
    if not item:
        logger.warning("Recommendation job not found: %s", job_id)
        return {"ok": False, "error": "job_not_found"}

    _update_job(item, status="running")
    try:
        credentials = get_user_broker_credentials(user_id)
        if not credentials or credentials.get("broker") != "alpaca":
            raise RuntimeError("Saved Alpaca connection is required for recommendation jobs.")

        api_key = credentials["api_key"]
        secret_key = credentials["secret_key"]
        trading_client = create_trading_client(api_key, secret_key)
        stock_data_client = create_stock_data_client(api_key, secret_key)
        option_data_client = create_option_data_client(api_key, secret_key)

        alpaca_account = get_safe_paper_account_summary(trading_client=trading_client)
        dashboard = get_dashboard_with_cash_context(
            user_id,
            alpaca_account,
            trading_client=trading_client,
        )
        capital = dashboard["capital"]
        effective_cash = get_effective_available_csp_cash(capital, alpaca_account)
        results = get_recommendation_results(
            user_id=user_id,
            total_capital=capital["total_capital"],
            current_open_positions=capital["open_position_count"],
            current_csp_capital_committed=capital["committed_capital"],
            external_available_csp_capital=effective_cash,
            portfolio_context={
                "capital": capital,
                "open_csp_positions": dashboard["open_positions"],
            },
            stock_data_client=stock_data_client,
            option_data_client=option_data_client,
        )
        if effective_cash <= 0 and alpaca_account.get("available_csp_cash") == 0:
            results["review"] = {
                "decision": "reject_all", "selected_contract": None,
                "summary": "Alpaca reports $0 options buying power, so no CSP can be backed right now.",
                "risk_note": "Options approval, open orders, or broker collateral rules may be limiting buying power.",
                "candidate_reviews": [],
            }

        candidates = candidates_to_records(results["candidates"])
        run = save_recommendation_run(
            user_id,
            candidates,
            results["review"],
            market_context=results.get("market_context"),
            strategy_rules=STRATEGY_RULES,
            portfolio_context=results.get("portfolio_context"),
            memory_context=results.get("memory_context"),
        )
        capture_current_csp_outcome_snapshots(
            user_id,
            dashboard.get("open_positions", []),
            context=compact_dashboard_memory_context(dashboard, trigger="recommendations_refresh"),
        )
        result = {
            "recommendation_run_id": run["id"], "approved_tickers": APPROVED_TICKERS,
            "company_names": COMPANY_NAMES, "strategy_rules": STRATEGY_RULES,
            "capital": attach_alpaca_cash_context(capital, alpaca_account),
            "dashboard": dashboard,
            "candidates": candidates, "review": results["review"],
        }
        _update_job(
            item,
            status="complete",
            result=result,
            error=None,
            completed_at=utc_now_text(),
        )
        return {"ok": True, "job_id": job_id}
    except Exception as error:
        logger.exception(
            "Recommendation job failed: %s (%s)",
            job_id,
            type(error).__name__,
        )
        _update_job(
            item,
            status="failed",
            error={
                "code": "recommendation_failed",
                "message": "Could not generate CSP recommendations. Please try again.",
            },
            completed_at=utc_now_text(),
        )
        return {"ok": False, "job_id": job_id, "error": "recommendation_failed"}


## Persist a job status transition while retaining its identity and TTL fields.
## All worker updates pass through this helper so timestamps remain consistent.
def _update_job(item, **changes):
    updated = {**item, **changes, "updated_at": utc_now_text()}
    put_item(updated)
    return updated


## Return only fields the polling frontend needs to render progress or a result.
## DynamoDB partition keys, ownership metadata, and expiration bookkeeping stay private.
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
