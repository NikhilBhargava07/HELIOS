## Portfolio and service-health HTTP routes.

from fastapi import APIRouter

from backend.api.services import get_dashboard_with_cash_context

router = APIRouter(prefix="/api", tags=["portfolio"])


@router.get("/health")
## Confirm that the FastAPI process is accepting requests.
def health_check():
    return {"status": "ok"}


@router.get("/dashboard")
## Return live Alpaca positions combined with Postgres history.
def get_dashboard():
    return get_dashboard_with_cash_context()
