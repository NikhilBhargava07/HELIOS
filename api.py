from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from main import (
    APPROVED_TICKERS,
    MAX_CSP_CAPITAL_PERCENT,
    MAX_OPEN_POSITIONS,
    STRATEGY_RULES,
    TOTAL_CAPITAL,
    get_recommendation_results,
)
from market_context import (
    ai_market_take,
    build_market_context,
    get_market_trends,
    get_recent_news,
)
from paper_store import (
    get_capital_summary,
    get_dashboard_data,
    record_user_decision,
    save_recommendation_run,
)


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
    decision = record_user_decision(
        decision_request.recommendation_run_id,
        decision_request.contract_symbol,
        decision_request.action,
        decision_request.note,
    )

    return {
        "decision": decision,
        "dashboard": get_dashboard_data(
            TOTAL_CAPITAL,
            MAX_CSP_CAPITAL_PERCENT,
            MAX_OPEN_POSITIONS,
        ),
    }


@app.get("/api/dashboard")
def get_dashboard():
    return get_dashboard_data(
        TOTAL_CAPITAL,
        MAX_CSP_CAPITAL_PERCENT,
        MAX_OPEN_POSITIONS,
    )


@app.get("/api/market/trends")
def get_trends():
    return {
        "trends": get_market_trends(APPROVED_TICKERS),
    }


@app.get("/api/market/news")
def get_news():
    return {
        "news": get_recent_news(APPROVED_TICKERS),
    }


@app.get("/api/market/context")
def get_context():
    return build_market_context(APPROVED_TICKERS)


@app.post("/api/market/take")
def post_market_take():
    context = build_market_context(APPROVED_TICKERS)

    return ai_market_take(context)


frontend_path = Path(__file__).with_name("frontend")

if frontend_path.exists():
    app.mount("/", StaticFiles(directory=frontend_path, html=True), name="frontend")
