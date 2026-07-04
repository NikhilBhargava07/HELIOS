## User profile and broker-credential setup HTTP routes.
##
## These routes are backend-only foundations for the later Profile UI. They
## require a Cognito-authenticated request, store visible profile metadata in
## DynamoDB, and keep broker secret keys in AWS Secrets Manager.

from fastapi import APIRouter, Request

from backend.api.schemas import BrokerProfileRequest
from backend.users.auth import require_authenticated_user
from backend.users.profiles import (
    get_user_profile,
    public_profile,
    save_broker_profile,
)

router = APIRouter(prefix="/api/profile", tags=["profile"])


@router.get("")
## Return the signed-in user's profile and broker connection status.
## The response may include the broker API key for display, but never includes the broker secret key or secret ARN.
def get_profile(request: Request):
    user = require_authenticated_user(request)
    profile = get_user_profile(user.user_id)

    return {
        "needs_onboarding": profile is None or not profile.get("broker_secret_arn"),
        "profile": public_profile(profile) or {
            "user_id": user.user_id,
            "email": user.email,
            "name": user.name,
            "broker_connected": False,
        },
    }


@router.post("/broker")
## Save or update the signed-in user's broker credentials.
## The broker API key is stored with the profile for display; the broker secret key is written to Secrets Manager and is never returned.
def post_broker_profile(payload: BrokerProfileRequest, request: Request):
    user = require_authenticated_user(request)
    profile = save_broker_profile(
        user=user,
        broker=payload.broker.strip().lower(),
        broker_api_key=payload.broker_api_key.strip(),
        broker_secret_key=payload.broker_secret_key.strip(),
    )

    return {
        "saved": True,
        "needs_onboarding": False,
        "profile": public_profile(profile),
    }
