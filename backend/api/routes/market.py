## Market trends, prices, news, context, and AI-take HTTP routes.

import logging

from fastapi import APIRouter, HTTPException, Request, Response

from backend.api.services import enqueue_worker, get_required_user_market_data_clients
from backend.users.auth import require_authenticated_user
from backend.config import APPROVED_TICKERS, COMPANY_NAMES, ETF_TICKERS
from backend.market.ai_take_jobs import create_market_take_job, get_market_take_job
from backend.market.context import build_market_context
from backend.market.earnings import get_earnings_calendar
from backend.market.news import NEWS_LOOKBACK_DAYS, get_recent_news, news_freshness_metadata
from backend.market.trends import get_latest_stock_prices, get_market_trends

router = APIRouter(prefix="/api/market", tags=["market"])
logger = logging.getLogger(__name__)


@router.get("/earnings")
## Return the stored earnings calendar for every approved company, soonest report first.
## Served from storage rather than the provider, because the calendar changes about once a
## quarter per company and a page view should not spend a rate limit re-asking.
def get_earnings(request: Request):
    require_authenticated_user(request)
    rows = get_earnings_calendar()

    for row in rows:
        row["company_name"] = COMPANY_NAMES.get(row.get("ticker_symbol"), row.get("ticker_symbol"))

    return {
        "earnings": rows,
        "company_names": COMPANY_NAMES,
        # Funds are absent by design, so the page can say so instead of looking incomplete.
        "excluded_funds": list(ETF_TICKERS),
        "refreshed_at": rows[0].get("refreshed_at") if rows else None,
    }


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
def get_news(response: Response, request: Request):
    require_authenticated_user(request)
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


@router.post("/take/jobs")
## Create and enqueue an asynchronous AI market-take job.
## The frontend receives a job id quickly, then polls the matching status endpoint until the result is ready.
def create_market_take_job_route(request: Request):
    user = require_authenticated_user(request)
    job = create_market_take_job(user.user_id)
    try:
        enqueue_worker("market_take", job["job_id"], user.user_id)
    except Exception as error:
        logger.exception(
            "Could not enqueue AI market-take job %s: %s",
            job["job_id"],
            type(error).__name__,
        )
        raise HTTPException(
            status_code=503,
            detail="Could not start the AI market-take job. Please try again.",
        ) from error
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
