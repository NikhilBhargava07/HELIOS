## Validate request bodies accepted by the HELIOS HTTP API.

from enum import Enum

from pydantic import BaseModel, Field


## Enumerate the user actions HELIOS accepts from recommendation cards.
## A strict enum prevents accidental or misspelled decision types from polluting memory.
class UserDecisionAction(str, Enum):

    DISCARD = "discard"
    PLACE_PAPER_ORDER = "place_paper_order"


## Validate the payload sent when a user places or discards a recommendation.
## The schema ties an action to the recommendation run and exact contract the user saw.
class UserDecisionRequest(BaseModel):

    recommendation_run_id: str
    contract_symbol: str
    action: UserDecisionAction
    note: str = ""


## Validate broker onboarding data after a user signs in with Google/Cognito.
## The frontend sends the broker API key and secret key once; the backend stores the secret key through the current secret-storage layer.
class BrokerProfileRequest(BaseModel):

    broker: str = "alpaca"
    broker_api_key: str
    broker_secret_key: str


## Enumerate the user's subjective assessment without replacing measured P&L.
## A mixed or satisfied assignment can therefore coexist with a financially losing option snapshot.
class TradeSatisfaction(str, Enum):

    VERY_DISSATISFIED = "very_dissatisfied"
    DISSATISFIED = "dissatisfied"
    MIXED = "mixed"
    SATISFIED = "satisfied"
    VERY_SATISFIED = "very_satisfied"


## Capture how the user felt about assignment for this specific CSP.
## This gives future recommendations direct preference evidence while keeping assignment economically unresolved until the shares are sold.
class AssignmentPreference(str, Enum):

    AVOID = "avoid"
    ACCEPTABLE = "acceptable"
    WELCOME = "welcome"
    NOT_APPLICABLE = "not_applicable"


## Limit feedback reasons to stable categories suitable for aggregation.
## Free-form detail still belongs in note, while these tags support reliable cross-trade preference counts.
class TradeFeedbackReason(str, Enum):

    PREMIUM = "premium"
    TIMING = "timing"
    VOLATILITY = "volatility"
    POSITION_SIZE = "position_size"
    ASSIGNMENT = "assignment"
    COMPANY_OUTLOOK = "company_outlook"
    MARKET_CONDITIONS = "market_conditions"
    NEWS_OR_EARNINGS = "news_or_earnings"
    EXECUTION = "execution"
    OTHER = "other"


## Validate explicit feedback attached to one known HELIOS or imported Alpaca order.
## The backend derives ticker and contract ownership from the order rather than trusting browser-submitted identifiers.
class TradeFeedbackRequest(BaseModel):

    opening_order_id: str = Field(min_length=1, max_length=200)
    satisfaction: TradeSatisfaction
    would_repeat: bool
    assignment_preference: AssignmentPreference = AssignmentPreference.NOT_APPLICABLE
    reason_tags: list[TradeFeedbackReason] = Field(default_factory=list, max_length=10)
    note: str = Field(default="", max_length=1000)
