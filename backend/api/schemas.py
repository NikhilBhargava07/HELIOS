## Validate request bodies accepted by the HELIOS HTTP API.

from enum import Enum

from pydantic import BaseModel


## Supported actions for a displayed recommendation candidate.
class UserDecisionAction(str, Enum):

    DISCARD = "discard"
    PLACE_PAPER_ORDER = "place_paper_order"


## Required browser payload for recording a candidate decision.
class UserDecisionRequest(BaseModel):

    recommendation_run_id: str
    contract_symbol: str
    action: UserDecisionAction
    note: str = ""


## Validated realized outcome supplied by broker sync or later UI tooling.
class TradeOutcomeRequest(BaseModel):

    decision_id: str
    status: str = "complete"
    outcome_label: str
    closing_cost: float | None = None
    realized_pnl: float | None = None
    assigned: bool | None = None
    expired_worthless: bool | None = None
    notes: str = ""
