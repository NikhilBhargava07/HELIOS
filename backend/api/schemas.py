## Validate request bodies accepted by the HELIOS HTTP API.

from enum import Enum

from pydantic import BaseModel


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
