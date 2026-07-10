## DynamoDB profile records for Cognito users and broker setup metadata.
##
## Profile records answer frontend questions like "is onboarding complete?"
## and backend questions like "which broker API key and secret ARN belong to
## this signed-in user?" The actual broker secret key stays in Secrets Manager.

from backend.memory.dynamodb_store import (
    from_dynamodb_value,
    get_item,
    put_item,
    utc_now_text,
)
from backend.users.auth import AuthenticatedUser
from backend.users.secrets import save_broker_secret


## Build the DynamoDB partition key for one Cognito user.
## Keeping all profile rows under USER_PROFILE#{sub} avoids mixing account setup data with strategy memory.
def user_profile_pk(user_id):
    return f"USER_PROFILE#{user_id}"


## Return a profile response that is safe for the frontend to display.
## The secret ARN is intentionally omitted because the UI should never see the secret key or where it is stored.
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
        "broker_connected": bool(profile.get("broker") and profile.get("broker_secret_arn")),
        "created_at": profile.get("created_at"),
        "updated_at": profile.get("updated_at"),
    }


## Fetch one user's raw profile record from DynamoDB.
## Backend broker code can use the raw record to find the secret ARN, while routes should return public_profile().
def get_user_profile(user_id):
    profile = get_item(user_profile_pk(user_id), "PROFILE")
    return from_dynamodb_value(profile) if profile else None


## Save or update the signed-in user's broker setup.
## The API key is stored in DynamoDB because the profile page may display it; the secret key is stored separately in Secrets Manager.
def save_broker_profile(user: AuthenticatedUser, broker, broker_api_key, broker_secret_key, broker_account=None):
    now = utc_now_text()
    existing_profile = get_user_profile(user.user_id) or {}
    secret_arn = save_broker_secret(user.user_id, broker, broker_secret_key)
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
        "broker_secret_arn": secret_arn,
        "broker_account_id": broker_account.get("account_id"),
        "broker_account_number": broker_account.get("account_number"),
        "broker_account_status": broker_account.get("status"),
        "broker_account_currency": broker_account.get("currency"),
        "created_at": existing_profile.get("created_at", now),
        "updated_at": now,
    }
    put_item(profile)
    return profile


## Return broker credentials for backend services that need user-specific Alpaca or future broker access.
## This function deliberately returns the secret only to backend callers, never to route serializers.
def get_user_broker_credentials(user_id):
    from backend.users.secrets import get_broker_secret

    profile = get_user_profile(user_id)
    if not profile or not profile.get("broker_secret_arn"):
        return None

    return {
        "broker": profile.get("broker"),
        "api_key": profile.get("broker_api_key"),
        "secret_key": get_broker_secret(profile["broker_secret_arn"]),
    }


## Create a broker trading client for a signed-in user's saved brokerage profile.
## Routes use this to read positions and submit paper orders against the user's own Alpaca account instead of the deployment-level fallback account.
def get_user_trading_client(user_id):
    from backend.broker.trading import create_trading_client

    credentials = get_user_broker_credentials(user_id)
    if not credentials:
        return None

    if credentials.get("broker") != "alpaca":
        return None

    return create_trading_client(credentials["api_key"], credentials["secret_key"])


## Create user-specific Alpaca market-data clients from the saved broker profile.
## Recommendation and trend routes use these clients so old APCA/ALPACA env keys cannot accidentally drive market scans.
def get_user_market_data_clients(user_id):
    from backend.broker.clients import create_option_data_client, create_stock_data_client

    credentials = get_user_broker_credentials(user_id)
    if not credentials:
        return None, None

    if credentials.get("broker") != "alpaca":
        return None, None

    return (
        create_stock_data_client(credentials["api_key"], credentials["secret_key"]),
        create_option_data_client(credentials["api_key"], credentials["secret_key"]),
    )
