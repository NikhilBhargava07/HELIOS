## DynamoDB profile records for Cognito users and broker setup metadata.
##
## Profile records answer frontend questions like "is onboarding complete?"
## and backend questions like "which broker API key and secret pointer belong to
## this signed-in user?" Secret storage is currently DynamoDB-backed for the
## private paper-trading prototype and should move to Secrets Manager later.

from backend.memory.dynamodb_store import (
    get_item,
    put_items,
    query_items,
    utc_now_text,
)
from backend.users.auth import AuthenticatedUser
from backend.users.secrets import save_broker_secret


## Build the DynamoDB partition key for one Cognito user.
## Keeping all profile rows under USER_PROFILE#{sub} avoids mixing account setup data with strategy memory.
def user_profile_pk(user_id):
    return f"USER_PROFILE#{user_id}"


CONNECTED_USERS_PK = "SYSTEM#CONNECTED_BROKER_USERS"


## Return a profile response that is safe for the frontend to display.
## The secret reference is intentionally omitted because the UI should never see the secret key or its storage location.
def public_profile(profile):
    if not profile:
        return None

    return {
        "user_id": profile["user_id"],
        "email": profile["email"],
        "name": profile.get("name"),
        "broker": profile.get("broker"),
        "broker_api_key": profile.get("broker_api_key"),
        "broker_account_id": profile.get("broker_account_id"),
        "broker_account_number": profile.get("broker_account_number"),
        "broker_account_status": profile.get("broker_account_status"),
        "broker_account_currency": profile.get("broker_account_currency"),
        "broker_connected": bool(
            profile.get("broker")
            and profile.get("broker_secret_ref")
        ),
        "created_at": profile.get("created_at"),
        "updated_at": profile.get("updated_at"),
    }


## Fetch one user's raw profile record from DynamoDB.
## Backend broker code can use the raw secret reference, while routes should return public_profile().
def get_user_profile(user_id):
    return get_item(user_profile_pk(user_id), "PROFILE")


## Save or update the signed-in user's broker setup.
## The API key is stored in DynamoDB because the profile page may display it; the secret key is stored separately through the secrets module.
def save_broker_profile(user: AuthenticatedUser, broker, broker_api_key, broker_secret_key, broker_account=None):
    now = utc_now_text()
    existing_profile = get_user_profile(user.user_id) or {}
    secret_ref = save_broker_secret(
        user.user_id,
        broker,
        broker_secret_key,
    )
    broker_account = broker_account or {}

    profile = {
        "pk": user_profile_pk(user.user_id),
        "sk": "PROFILE",
        "item_type": "user_profile",
        "user_id": user.user_id,
        "email": user.email,
        "name": user.name,
        "broker": broker,
        "broker_api_key": broker_api_key,
        "broker_secret_ref": secret_ref,
        "broker_account_id": broker_account.get("account_id"),
        "broker_account_number": broker_account.get("account_number"),
        "broker_account_status": broker_account.get("status"),
        "broker_account_currency": broker_account.get("currency"),
        "created_at": existing_profile.get("created_at", now),
        "updated_at": now,
    }
    put_items([
        profile,
        {
            "pk": CONNECTED_USERS_PK,
            "sk": f"USER#{user.user_id}",
            "item_type": "connected_broker_user",
            "user_id": user.user_id,
            "broker": broker,
            "updated_at": now,
        },
    ])
    return profile


## Return broker credentials for backend services that need user-specific Alpaca or future broker access.
## This function deliberately returns the secret only to backend callers, never to route serializers.
def get_user_broker_credentials(user_id):
    from backend.users.secrets import get_broker_secret

    profile = get_user_profile(user_id)
    if not profile:
        return None

    secret_ref = profile.get("broker_secret_ref")
    if not secret_ref:
        return None

    return {
        "broker": profile.get("broker"),
        "api_key": profile.get("broker_api_key"),
        "secret_key": get_broker_secret(secret_ref),
    }


## List users with a connected broker for scheduled lifecycle observations.
## The small system registry avoids an expensive full-table scan and contains only opaque Cognito ids, never broker credentials.
def list_connected_broker_user_ids(limit=500):
    return [
        item["user_id"]
        for item in query_items(
            CONNECTED_USERS_PK,
            "USER#",
            limit=limit,
        )
        if item.get("user_id")
    ]
