## Inspect and refresh episodic, outcome, and user-profile memory.

from fastapi import APIRouter, Query

from backend.api.schemas import TradeOutcomeRequest
from backend.api.services import compact_dashboard_memory_context, get_dashboard_with_cash_context
from backend.memory.learning_user import build_memory_context
from backend.memory.observations import (
    capture_current_csp_outcome_snapshots,
    capture_due_candidate_observations,
    get_recent_outcome_snapshots,
    record_trade_outcome,
)


router = APIRouter(prefix="/api/memory", tags=["memory"])


@router.get("/context")
## Return the current learning-memory summary used by the agent.
## This endpoint helps inspect how episodic decisions, outcome patterns, and user preferences are being summarized.
def get_memory_context(tickers: list[str] = Query(default=[])):
    return build_memory_context([ticker.upper() for ticker in tickers])


@router.post("/observe")
## Capture delayed outcome observations for prior recommendation candidates.
## Scheduled runs can use this to learn how candidates behaved after 1 day, 5 days, and later checkpoints.
def observe_due_candidates():
    return capture_due_candidate_observations()


@router.post("/outcome-snapshots")
## Capture nuanced outcome snapshots for currently open CSP positions.
## The endpoint reads live Alpaca positions, classifies financial pain versus assignment acceptability, and stores the result in DynamoDB memory.
def capture_open_position_outcome_snapshots():
    dashboard = get_dashboard_with_cash_context()
    return capture_current_csp_outcome_snapshots(
        dashboard.get("open_positions", []),
        context=compact_dashboard_memory_context(dashboard, trigger="manual_memory_snapshot"),
    )


@router.get("/outcome-snapshots")
## Return recent current-position outcome snapshots saved in HELIOS memory.
## This is the inspection endpoint for confirming the learning layer is recording active CSP consequences.
def list_recent_outcome_snapshots(limit: int = Query(default=20, ge=1, le=100)):
    return {
        "snapshots": get_recent_outcome_snapshots(limit=limit),
        "limit": limit,
    }


@router.post("/outcomes")
## Manually record the outcome of a paper trade.
## This gives HELIOS a structured way to connect recommendation reasoning with actual trade results.
def post_trade_outcome(request: TradeOutcomeRequest):
    return record_trade_outcome(
        decision_id=request.decision_id,
        status=request.status,
        outcome_label=request.outcome_label,
        closing_cost=request.closing_cost,
        realized_pnl=request.realized_pnl,
        assigned=request.assigned,
        expired_worthless=request.expired_worthless,
        notes=request.notes,
    )
