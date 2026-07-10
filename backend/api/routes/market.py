## Market trends, prices, news, context, and AI-take HTTP routes.

import json
import os

import boto3
from fastapi import APIRouter, HTTPException, Request, Response

from backend.api.services import (
    get_dashboard_with_cash_context,
    get_required_user_market_data_clients,
    get_required_user_trading_client,
)
from backend.users.auth import require_authenticated_user
from backend.config import APPROVED_TICKERS, COMPANY_NAMES
from backend.market.ai_take import ai_market_take
from backend.market.ai_take_jobs import create_market_take_job, get_market_take_job
from backend.market.context import build_market_context
from backend.market.news import NEWS_LOOKBACK_DAYS, get_recent_news, news_freshness_metadata
from backend.market.trends import get_latest_stock_prices, get_market_trends
from backend.memory.recommendations import get_latest_recommendation_run

router = APIRouter(prefix="/api/market", tags=["market"])


## Start the Lambda background worker for an AI market-take job.
## This avoids API Gateway timeouts by returning a job id immediately while the OpenAI call continues asynchronously.
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
## Return recent price trends for the approved ticker universe.
## The frontend uses this for Market Trends cards and the AI prompt uses it as market context for CSP risk.
def get_trends(request: Request):
    stock_data_client, _ = get_required_user_market_data_clients(request)
    trends = get_market_trends(APPROVED_TICKERS, stock_data_client=stock_data_client)
    prices = get_latest_stock_prices(APPROVED_TICKERS, stock_data_client=stock_data_client)
    for trend in trends:
        latest = prices.get(trend["ticker"], {})
        trend.update({
            "company_name": COMPANY_NAMES.get(trend["ticker"], trend["ticker"]),
            "current_price": latest.get("price"),
            "price_timestamp": latest.get("timestamp"),
        })
    return {"trends": trends, "prices": prices, "company_names": COMPANY_NAMES}


@router.get("/prices")
## Return lightweight latest-price updates for already loaded trend cards.
## This keeps the UI feeling live without re-fetching full historical windows every few seconds.
def get_prices(request: Request):
    stock_data_client, _ = get_required_user_market_data_clients(request)
    return {
        "prices": get_latest_stock_prices(APPROVED_TICKERS, stock_data_client=stock_data_client),
        "company_names": COMPANY_NAMES,
    }


@router.get("/news")
## Return filtered current-news headlines from approved and reputable sources.
## News items include freshness metadata and no-store headers so the user can tell when HELIOS checked live sources.
def get_news(response: Response):
    news = get_recent_news(APPROVED_TICKERS)
    response.headers["Cache-Control"] = "no-store, max-age=0"
    response.headers["Pragma"] = "no-cache"
    return {
        "news": news,
        **news_freshness_metadata(news, NEWS_LOOKBACK_DAYS),
    }


@router.get("/context")
## Return combined trend and news context for debugging or future UI panels.
## Keeping this route separate lets HELIOS inspect the evidence package without triggering an AI review.
def get_context(request: Request):
    stock_data_client, _ = get_required_user_market_data_clients(request)
    return build_market_context(APPROVED_TICKERS, stock_data_client=stock_data_client)


@router.post("/take")
## Produce a synchronous AI market take for local development.
## The hosted frontend normally uses the async job route because OpenAI responses can exceed API Gateway timing limits.
def post_market_take(request: Request):
    stock_data_client, _ = get_required_user_market_data_clients(request)
    trading_client = get_required_user_trading_client(request)
    context = build_market_context(APPROVED_TICKERS, stock_data_client=stock_data_client)
    dashboard = get_dashboard_with_cash_context(trading_client=trading_client)
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
## Create and enqueue an asynchronous AI market-take job.
## The frontend receives a job id quickly, then polls the matching status endpoint until the result is ready.
def create_market_take_job_route(request: Request):
    user = require_authenticated_user(request)
    job = create_market_take_job(user.user_id)
    try:
        enqueue_market_take_worker(job["job_id"])
    except Exception as error:
        raise HTTPException(status_code=503, detail=f"Could not start AI job: {type(error).__name__}") from error
    return job


@router.get("/take/jobs/{job_id}")
## Return the latest status or result for an AI market-take job.
## This route supports the polling loop that keeps long reasoning calls from freezing the UI.
def get_market_take_job_route(job_id, request: Request):
    user = require_authenticated_user(request)
    job = get_market_take_job(job_id, user_id=user.user_id)
    if not job:
        raise HTTPException(status_code=404, detail="AI market-take job not found.")
    return job

