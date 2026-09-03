## Run user-scoped CSP recommendation scans outside API Gateway's request timeout.
##
## The multi-ticker option scan plus AI review can exceed API Gateway's 30-second
## limit, so the browser creates a short-lived DynamoDB job, Lambda performs the
## scan asynchronously, and the browser polls until the result is ready. This is
## the same pattern the AI market-take feature already uses.

import logging

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
from backend.broker.trading import create_trading_client, get_paper_orders
from backend.config import (
    APPROVED_TICKERS,
    COMPANY_NAMES,
    STRATEGY_RULES,
)
from backend.memory.dynamodb_store import utc_now_text
from backend.memory.jobs import (
    create_job,
    public_job,
    read_job_item,
    update_job,
)
from backend.memory.observations import capture_current_csp_outcome_snapshots
from backend.memory.outcome_jobs import run_outcome_observation
from backend.memory.recommendations import save_recommendation_run
from backend.strategy.recommender import get_recommendation_results
from backend.users.profiles import get_user_broker_credentials

logger = logging.getLogger(__name__)


JOB_SORT_KEY_PREFIX = "RECOMMENDATION_JOB"


## Create a pending recommendation-scan job inside the authenticated user's partition.
## The shared job store owns the record shape so every job type polls identically.
def create_recommendation_job(user_id):
    return create_job(user_id, JOB_SORT_KEY_PREFIX, "recommendation_job")


## Fetch one job only from the requesting user's private partition.
## A job id from another account therefore behaves exactly like a missing job.
def get_recommendation_job(job_id, user_id):
    item = read_job_item(user_id, JOB_SORT_KEY_PREFIX, job_id)
    return public_job(item) if item else None


## Execute one background CSP scan for its owner and store the full response payload.
## Credentials are loaded once, then used to build the trading and market-data clients the scan needs.
def run_recommendation_job(job_id, user_id):
    item = read_job_item(user_id, JOB_SORT_KEY_PREFIX, job_id)
    if not item:
        logger.warning("Recommendation job not found: %s", job_id)
        return {"ok": False, "error": "job_not_found"}

    update_job(item, status="running")
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
        broker_orders = get_paper_orders(limit=500, trading_client=trading_client)
        dashboard = get_dashboard_with_cash_context(
            user_id,
            alpaca_account,
            trading_client=trading_client,
            broker_orders=broker_orders,
        )
        learning_refresh = None
        try:
            learning_refresh = run_outcome_observation(
                user_id,
                trigger="recommendation_scan",
                include_market_context=False,
                trading_client=trading_client,
                stock_data_client=stock_data_client,
                account=alpaca_account,
                positions=dashboard.get("all_positions"),
                broker_orders=broker_orders,
                credentials=credentials,
            )
        except Exception as error:
            logger.warning(
                "Pre-scan outcome refresh failed without blocking recommendations: %s",
                type(error).__name__,
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
        result = {
            "recommendation_run_id": run["id"], "approved_tickers": APPROVED_TICKERS,
            "company_names": COMPANY_NAMES, "strategy_rules": STRATEGY_RULES,
            "capital": attach_alpaca_cash_context(capital, alpaca_account),
            "dashboard": dashboard,
            "candidates": candidates, "review": results["review"],
            "learning_refresh": learning_refresh,
        }
        update_job(
            item,
            status="complete",
            result=result,
            error=None,
            completed_at=utc_now_text(),
        )

        # Outcome snapshots are auxiliary memory capture; the sync route ran them as a
        # post-response background task, so a snapshot failure must not fail the scan.
        try:
            snapshot_context = compact_dashboard_memory_context(
                dashboard,
                trigger="recommendations_refresh",
            )
            snapshot_context["market_context"] = results.get("market_context") or {}
            capture_current_csp_outcome_snapshots(
                user_id,
                dashboard.get("open_positions", []),
                context=snapshot_context,
            )
        except Exception as error:
            logger.warning("Outcome snapshot capture failed after scan: %s", type(error).__name__)

        return {"ok": True, "job_id": job_id}
    except Exception as error:
        logger.exception(
            "Recommendation job failed: %s (%s)",
            job_id,
            type(error).__name__,
        )
        update_job(
            item,
            status="failed",
            error={
                "code": "recommendation_failed",
                # Surface the real cause so the page explains the failure without CloudWatch digging.
                "message": f"CSP scan failed — {type(error).__name__}: {str(error)[:300]}",
            },
            completed_at=utc_now_text(),
        )
        return {"ok": False, "job_id": job_id, "error": "recommendation_failed"}


