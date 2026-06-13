from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from main import (
    APPROVED_TICKERS,
    COMPANY_NAMES,
    MAX_CSP_CAPITAL_PERCENT,
    MAX_OPEN_POSITIONS,
    STRATEGY_RULES,
    TOTAL_CAPITAL,
    get_recommendation_results,
)
from market_context import (
    NEWS_LOOKBACK_DAYS,
    ai_market_take,
    build_market_context,
    get_latest_stock_prices,
    get_market_trends,
    get_recent_news,
)
from paper_store import (
    find_candidate,
    find_recommendation_run,
    get_capital_summary,
    get_dashboard_data,
    load_store,
    record_user_decision,
    save_recommendation_run,
)
from order_manager import submit_cash_secured_put_order


app = FastAPI(title="CSP Agent API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class UserDecisionRequest(BaseModel):
    recommendation_run_id: str
    contract_symbol: str
    action: str
    note: str = ""


def get_recommendation_run_from_store(run_id):
    store = load_store()
    run = find_recommendation_run(store, run_id)

    if run is None:
        raise ValueError("Recommendation run not found.")

    return run


def get_candidate_from_run(run, contract_symbol):
    candidate = find_candidate(run, contract_symbol)

    if candidate is None:
        raise ValueError("Candidate not found in recommendation run.")

    return candidate


def candidates_to_records(candidates):
    if candidates.empty:
        return []

    display_columns = [
        "tickerSymbol",
        "contractSymbol",
        "expiration",
        "DTE",
        "strike",
        "currentStockPrice",
        "delta",
        "ivPercent",
        "spread",
        "premiumIfSoldAtBid",
        "cashRequired",
        "breakevenPrice",
        "returnOnCashPercent",
    ]

    records = candidates[display_columns].to_dict(orient="records")

    for record in records:
        for key, value in record.items():
            if hasattr(value, "item"):
                record[key] = value.item()

        record["companyName"] = COMPANY_NAMES.get(record["tickerSymbol"], record["tickerSymbol"])

    return records


@app.get("/api/health")
def health_check():
    return {"status": "ok"}


@app.get("/api/recommendations")
def get_recommendations():
    capital_summary = get_capital_summary(
        TOTAL_CAPITAL,
        MAX_CSP_CAPITAL_PERCENT,
        MAX_OPEN_POSITIONS,
    )
    results = get_recommendation_results(
        current_open_positions=capital_summary["open_position_count"],
        current_csp_capital_committed=capital_summary["committed_capital"],
    )
    candidates = candidates_to_records(results["candidates"])
    recommendation_run = save_recommendation_run(candidates, results["review"])

    return {
        "recommendation_run_id": recommendation_run["id"],
        "approved_tickers": APPROVED_TICKERS,
        "company_names": COMPANY_NAMES,
        "strategy_rules": STRATEGY_RULES,
        "capital": capital_summary,
        "dashboard": get_dashboard_data(
            TOTAL_CAPITAL,
            MAX_CSP_CAPITAL_PERCENT,
            MAX_OPEN_POSITIONS,
        ),
        "candidates": candidates,
        "review": results["review"],
    }


@app.post("/api/decisions")
def post_user_decision(decision_request: UserDecisionRequest):
    alpaca_order = None
    order_error = None

    if decision_request.action == "place_paper_order":
        store_action = "place_paper_order"
        try:
            run = get_recommendation_run_from_store(decision_request.recommendation_run_id)
            candidate = get_candidate_from_run(run, decision_request.contract_symbol)
            alpaca_order = submit_cash_secured_put_order(candidate)
        except Exception as error:
            store_action = "place_paper_order_failed"
            order_error = str(error)

            decision = record_user_decision(
                decision_request.recommendation_run_id,
                decision_request.contract_symbol,
                store_action,
                decision_request.note,
                order_error=order_error,
            )

            return {
                "decision": decision,
                "order_submitted": False,
                "order_error": order_error,
                "dashboard": get_dashboard_data(
                    TOTAL_CAPITAL,
                    MAX_CSP_CAPITAL_PERCENT,
                    MAX_OPEN_POSITIONS,
                ),
            }
    else:
        store_action = decision_request.action

    decision = record_user_decision(
        decision_request.recommendation_run_id,
        decision_request.contract_symbol,
        store_action,
        decision_request.note,
        alpaca_order=alpaca_order,
        order_error=order_error,
    )

    return {
        "decision": decision,
        "order_submitted": alpaca_order is not None,
        "alpaca_order": alpaca_order,
        "dashboard": get_dashboard_data(
            TOTAL_CAPITAL,
            MAX_CSP_CAPITAL_PERCENT,
            MAX_OPEN_POSITIONS,
        ),
    }


@app.get("/api/dashboard")
def get_dashboard():
    dashboard = get_dashboard_data(
        TOTAL_CAPITAL,
        MAX_CSP_CAPITAL_PERCENT,
        MAX_OPEN_POSITIONS,
    )
    dashboard["company_names"] = COMPANY_NAMES

    return dashboard


@app.get("/api/market/trends")
def get_trends():
    trends = get_market_trends(APPROVED_TICKERS)
    prices = get_latest_stock_prices(APPROVED_TICKERS)

    for trend in trends:
        latest = prices.get(trend["ticker"], {})
        trend["company_name"] = COMPANY_NAMES.get(trend["ticker"], trend["ticker"])
        trend["current_price"] = latest.get("price")
        trend["price_timestamp"] = latest.get("timestamp")

    return {
        "trends": trends,
        "prices": prices,
        "company_names": COMPANY_NAMES,
    }


@app.get("/api/market/prices")
def get_prices():
    return {
        "prices": get_latest_stock_prices(APPROVED_TICKERS),
        "company_names": COMPANY_NAMES,
    }


@app.get("/api/market/news")
def get_news():
    return {
        "news": get_recent_news(APPROVED_TICKERS),
        "lookback_days": NEWS_LOOKBACK_DAYS,
    }


@app.get("/api/market/context")
def get_context():
    return build_market_context(APPROVED_TICKERS)


@app.post("/api/market/take")
def post_market_take():
    context = build_market_context(APPROVED_TICKERS)
    take = ai_market_take(context)
    take["company_names"] = COMPANY_NAMES

    return take


frontend_path = Path(__file__).with_name("frontend")

if frontend_path.exists():
    app.mount("/", StaticFiles(directory=frontend_path, html=True), name="frontend")
