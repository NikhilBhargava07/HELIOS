## Market trends, prices, news, context, and AI-take HTTP routes.

from fastapi import APIRouter

from backend.api.services import get_dashboard_with_cash_context
from backend.config import APPROVED_TICKERS, COMPANY_NAMES
from backend.market.ai_take import ai_market_take
from backend.market.context import build_market_context
from backend.market.news import NEWS_LOOKBACK_DAYS, get_recent_news
from backend.market.trends import get_latest_stock_prices, get_market_trends
from backend.memory.recommendations import get_latest_recommendation_run

router = APIRouter(prefix="/api/market", tags=["market"])


@router.get("/trends")
def get_trends():
    ## Return multi-period trends enriched with current prices and names.
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
def get_prices():
    ## Return latest batched prices for lightweight frontend refreshes.
    return {
        "prices": get_latest_stock_prices(APPROVED_TICKERS),
        "company_names": COMPANY_NAMES,
    }


@router.get("/news")
def get_news():
    ## Return recent sanitized RSS headlines within the configured window.
    return {
        "news": get_recent_news(APPROVED_TICKERS),
        "lookback_days": NEWS_LOOKBACK_DAYS,
    }


@router.get("/context")
def get_context():
    ## Return the combined trend and news context used by the AI.
    return build_market_context(APPROVED_TICKERS)


@router.post("/take")
def post_market_take():
    ## Create an AI take centered on current positions and latest candidates.
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
