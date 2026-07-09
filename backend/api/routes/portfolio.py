## Portfolio and service-health HTTP routes.

from fastapi import APIRouter, Request

from backend.api.services import get_dashboard_with_cash_context, get_optional_user_trading_client

router = APIRouter(prefix="/api", tags=["portfolio"])


@router.get("/health")
## Lightweight health endpoint for deployment smoke tests.
## API Gateway and CloudFront checks can call this without touching Alpaca, OpenAI, or DynamoDB.
def health_check():
    return {"status": "ok"}


@router.get("/dashboard")
## Return the live portfolio and paper-ledger view for the Capital & Positions page.
## The route asks the service layer to merge Alpaca state with HELIOS memory so the frontend has one stable object to render.
def get_dashboard(request: Request):
    trading_client = get_optional_user_trading_client(request)
    return get_dashboard_with_cash_context(trading_client=trading_client)
