## Portfolio and service-health HTTP routes.

from fastapi import APIRouter

from backend.api.services import get_dashboard_with_cash_context

router = APIRouter(prefix="/api", tags=["portfolio"])


@router.get("/health")
def health_check():
    ## Confirm that the FastAPI process is accepting requests.
    return {"status": "ok"}


@router.get("/dashboard")
def get_dashboard():
    ## Return live Alpaca positions combined with Postgres history.
    return get_dashboard_with_cash_context()
