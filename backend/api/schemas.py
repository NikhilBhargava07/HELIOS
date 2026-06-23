"""Validate request bodies accepted by the CSP Agent HTTP API."""

from enum import Enum

from pydantic import BaseModel


class UserDecisionAction(str, Enum):
    """Supported actions for a displayed recommendation candidate."""

    DISCARD = "discard"
    PLACE_PAPER_ORDER = "place_paper_order"


class UserDecisionRequest(BaseModel):
    """Required browser payload for recording a candidate decision."""

    recommendation_run_id: str
    contract_symbol: str
    action: UserDecisionAction
    note: str = ""


class TradeOutcomeRequest(BaseModel):
    """Validated realized outcome supplied by broker sync or later UI tooling."""

    decision_id: str
    status: str = "complete"
    outcome_label: str
    closing_cost: float | None = None
    realized_pnl: float | None = None
    assigned: bool | None = None
    expired_worthless: bool | None = None
    notes: str = ""
