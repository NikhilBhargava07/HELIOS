## Market trends, prices, news, context, and AI-take HTTP routes.

import json
import os

import boto3
from fastapi import APIRouter, HTTPException

from backend.api.services import get_dashboard_with_cash_context
from backend.config import APPROVED_TICKERS, COMPANY_NAMES
from backend.market.ai_take import ai_market_take
from backend.market.ai_take_jobs import create_market_take_job, get_market_take_job
from backend.market.context import build_market_context
from backend.market.news import NEWS_LOOKBACK_DAYS, get_recent_news
from backend.market.trends import get_latest_stock_prices, get_market_trends
from backend.memory.recommendations import get_latest_recommendation_run

router = APIRouter(prefix="/api/market", tags=["market"])


## Ask Lambda to run the market-take job outside the API Gateway request.
def enqueue_market_take_worker(job_id):
    function_name = os.getenv("AWS_LAMBDA_FUNCTION_NAME")
    if not function_name:
        raise RuntimeError("AWS_LAMBDA_FUNCTION_NAME is required for async market-take jobs.")

    boto3.client("lambda").invoke(
        FunctionName=function_name,
        InvocationType="Event",
        Payload=json.dumps({"worker_action": "market_take", "job_id": job_id}).encode("utf-8"),
    )



@router.get("/trends")
## Return multi-period trends enriched with current prices and names.
def get_trends():
    trends = get_market_trends(APPROVED_TICKERS)
    prices = get_latest_stock_prices(APPROVED_TICKERS)
    for trend in trends:
        latest = prices.get(trend["ticker"], {})
        trend.update({
            "company_name": COMPANY_NAMES.get(trend["ticker"], trend["ticker"]),
            "current_price": latest.get("price"),
            "price_timestamp": latest.get("timestamp"),
        })
    return {"trends": trends, "prices": prices, "company_names": COMPANY_NAMES}


@router.get("/prices")
## Return latest batched prices for lightweight frontend refreshes.
def get_prices():
    return {
        "prices": get_latest_stock_prices(APPROVED_TICKERS),
        "company_names": COMPANY_NAMES,
    }


@router.get("/news")
## Return recent sanitized RSS headlines within the configured window.
def get_news():
    return {
        "news": get_recent_news(APPROVED_TICKERS),
        "lookback_days": NEWS_LOOKBACK_DAYS,
    }


@router.get("/context")
## Return the combined trend and news context used by the AI.
def get_context():
    return build_market_context(APPROVED_TICKERS)


@router.post("/take")
## Create an AI take centered on current positions and latest candidates.
def post_market_take():
    context = build_market_context(APPROVED_TICKERS)
    dashboard = get_dashboard_with_cash_context()
    context["portfolio"] = {
        "open_csp_positions": dashboard["open_positions"],
        "capital": dashboard["capital"],
        "position_source": dashboard["position_source"],
    }
    context["latest_recommendation"] = get_latest_recommendation_run()
    take = ai_market_take(context)
    take["company_names"] = COMPANY_NAMES
    return take

@router.post("/take/jobs")
## Create an async AI market-take job and return immediately for frontend polling.
def create_market_take_job_route():
    job = create_market_take_job()
    try:
        enqueue_market_take_worker(job["job_id"])
    except Exception as error:
        raise HTTPException(status_code=503, detail=f"Could not start AI job: {type(error).__name__}") from error
    return job


@router.get("/take/jobs/{job_id}")
## Return current status or final result for one AI market-take job.
def get_market_take_job_route(job_id):
    job = get_market_take_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="AI market-take job not found.")
    return job

