## User profile and broker-credential setup HTTP routes.
##
## These routes are backend-only foundations for the later Profile UI. They
## require a Cognito-authenticated request and store broker setup data in
## DynamoDB for the private paper-trading prototype. Broker secret storage must
## move to AWS Secrets Manager before public launch or live-money trading.

import logging

from fastapi import APIRouter, HTTPException, Request

from backend.api.schemas import BrokerProfileRequest
from backend.broker.trading import validate_alpaca_paper_credentials
from backend.users.auth import require_authenticated_user
from backend.users.profiles import (
    get_user_profile,
    public_profile,
    save_broker_profile,
)

router = APIRouter(prefix="/api/profile", tags=["profile"])
logger = logging.getLogger(__name__)


@router.get("")
## Return the signed-in user's profile and broker connection status.
## The response may include the broker API key for display, but never includes the broker secret key or storage reference.
def get_profile(request: Request):
    try:
        user = require_authenticated_user(request)
        profile = get_user_profile(user.user_id)
    except HTTPException:
        raise
    except Exception as error:
        logger.exception("Profile load failed before response: %s", type(error).__name__)
        raise HTTPException(
            status_code=503,
            detail="Could not load profile storage. Check Lambda DynamoDB access and table configuration.",
        ) from None

    return {
        "needs_onboarding": (
            profile is None
            or not profile.get("broker_secret_ref")
        ),
        "profile": public_profile(profile) or {
            "user_id": user.user_id,
            "email": user.email,
            "name": user.name,
            "broker_connected": False,
        },
    }


@router.post("/broker")
## Save or update the signed-in user's broker credentials.
## The broker API key is stored with the profile for display; the broker secret key is stored through the secrets module and is never returned.
def post_broker_profile(payload: BrokerProfileRequest, request: Request):
    try:
        user = require_authenticated_user(request)
        broker = payload.broker.strip().lower()
        broker_api_key = payload.broker_api_key.strip()
        broker_secret_key = payload.broker_secret_key.strip()
    except HTTPException:
        raise
    except Exception as error:
        logger.exception("Broker profile request setup failed: %s", type(error).__name__)
        raise HTTPException(
            status_code=400,
            detail="Could not read the broker setup form. Check that broker, API key, and secret key were submitted.",
        ) from None

    if broker != "alpaca":
        raise HTTPException(
            status_code=400,
            detail="Alpaca paper trading is the only supported brokerage right now.",
        )

    try:
        broker_account = validate_alpaca_paper_credentials(broker_api_key, broker_secret_key)
    except Exception:
        logger.info("Alpaca credential validation failed for user %s", user.user_id)
        raise HTTPException(
            status_code=400,
            detail="Alpaca rejected those API credentials. Check that they belong to a paper-trading account.",
        ) from None

    try:
        profile = save_broker_profile(
            user=user,
            broker=broker,
            broker_api_key=broker_api_key,
            broker_secret_key=broker_secret_key,
            broker_account=broker_account,
        )
    except Exception as error:
        logger.exception("Broker profile save failed for user %s: %s", user.user_id, type(error).__name__)
        raise HTTPException(
            status_code=503,
            detail="Could not save broker profile storage. Check Lambda DynamoDB access and table configuration.",
        ) from None

    return {
        "saved": True,
        "needs_onboarding": False,
        "profile": public_profile(profile),
    }
