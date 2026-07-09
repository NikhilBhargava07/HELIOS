## Recommendation generation and user-decision HTTP routes.

from fastapi import APIRouter, BackgroundTasks, Request

from backend.api.schemas import UserDecisionAction, UserDecisionRequest
from backend.api.services import (
    attach_alpaca_cash_context,
    candidates_to_records,
    compact_dashboard_memory_context,
    get_dashboard_with_cash_context,
    get_effective_available_csp_cash,
    get_optional_user_trading_client,
    get_safe_paper_account_summary,
    require_candidate,
    require_recommendation_run,
)
from backend.broker.trading import submit_cash_secured_put_order
from backend.config import APPROVED_TICKERS, COMPANY_NAMES, STRATEGY_RULES
from backend.memory.recommendations import save_recommendation_run
from backend.memory.observations import (
    capture_current_csp_outcome_snapshots,
    capture_due_candidate_observations,
)
from backend.memory.trades import record_user_decision
from backend.strategy.recommender import get_recommendation_results

router = APIRouter(prefix="/api", tags=["recommendations"])


@router.get("/recommendations")
## Generate a fresh CSP recommendation run for the frontend.
## The route scans candidates, adds market and memory context, asks the review agent, saves the run, and returns dashboard data in one response.
def get_recommendations(background_tasks: BackgroundTasks, request: Request):
    trading_client = get_optional_user_trading_client(request)
    alpaca_account = get_safe_paper_account_summary(trading_client=trading_client)
    dashboard = get_dashboard_with_cash_context(alpaca_account, trading_client=trading_client)
    capital = dashboard["capital"]
    effective_cash = get_effective_available_csp_cash(capital, alpaca_account)
    results = get_recommendation_results(
        current_open_positions=capital["open_position_count"],
        current_csp_capital_committed=capital["committed_capital"],
        external_available_csp_capital=effective_cash,
        portfolio_context={
            "capital": capital,
            "open_csp_positions": dashboard["open_positions"],
        },
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
        candidates,
        results["review"],
        market_context=results.get("market_context"),
        strategy_rules=STRATEGY_RULES,
        portfolio_context=results.get("portfolio_context"),
        memory_context=results.get("memory_context"),
    )
    background_tasks.add_task(capture_due_candidate_observations)
    background_tasks.add_task(
        capture_current_csp_outcome_snapshots,
        dashboard.get("open_positions", []),
        context=compact_dashboard_memory_context(dashboard, trigger="recommendations_refresh"),
    )
    return {
        "recommendation_run_id": run["id"], "approved_tickers": APPROVED_TICKERS,
        "company_names": COMPANY_NAMES, "strategy_rules": STRATEGY_RULES,
        "capital": attach_alpaca_cash_context(capital, alpaca_account),
        "dashboard": dashboard,
        "candidates": candidates, "review": results["review"],
    }


@router.post("/decisions")
## Record a user decision from the recommendation cards.
## Paper-place actions are submitted to Alpaca first, then the decision is stored in memory so later learning can compare recommendation versus user behavior.
def post_user_decision(request: UserDecisionRequest, http_request: Request):
    trading_client = get_optional_user_trading_client(http_request)
    alpaca_order = None
    alpaca_account = None
    order_error = None
    store_action = request.action.value

    if request.action == UserDecisionAction.PLACE_PAPER_ORDER:
        try:
            run = require_recommendation_run(request.recommendation_run_id)
            candidate = require_candidate(run, request.contract_symbol)
            alpaca_account = get_safe_paper_account_summary(trading_client=trading_client)
            available_cash = alpaca_account.get("available_csp_cash")
            cash_required = float(candidate.get("cashRequired") or 0)
            if available_cash is not None and cash_required > available_cash:
                raise ValueError(
                    f"Insufficient Alpaca paper buying power. This CSP requires ${cash_required:,.2f}, "
                    f"but Alpaca reports ${available_cash:,.2f} available."
                )
            alpaca_order = submit_cash_secured_put_order(candidate, trading_client=trading_client)
        except Exception as error:
            store_action = "place_paper_order_failed"
            order_error = str(error)
            decision = record_user_decision(
                request.recommendation_run_id, request.contract_symbol,
                store_action, request.note, order_error=order_error,
            )
            return {
                "decision": decision, "order_submitted": False,
                "order_error": order_error, "refresh_recommendations": True,
                "dashboard": get_dashboard_with_cash_context(alpaca_account, trading_client=trading_client),
            }

    decision = record_user_decision(
        request.recommendation_run_id, request.contract_symbol, store_action,
        request.note, alpaca_order=alpaca_order, order_error=order_error,
    )
    return {
        "decision": decision, "order_submitted": alpaca_order is not None,
        "alpaca_order": alpaca_order,
        "refresh_recommendations": request.action == UserDecisionAction.PLACE_PAPER_ORDER,
        "dashboard": get_dashboard_with_cash_context(trading_client=trading_client),
    }
