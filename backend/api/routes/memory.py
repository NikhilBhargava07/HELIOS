## Inspect and refresh episodic, outcome, and user-profile memory.

from fastapi import APIRouter, Query

from backend.api.schemas import TradeOutcomeRequest
from backend.memory.learning_user import build_memory_context
from backend.memory.observations import (
    capture_due_candidate_observations,
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
