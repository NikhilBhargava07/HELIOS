## Store and retrieve broker secrets for the paper-trading prototype.
##
## TEMPORARY PROTOTYPE STORAGE:
## HELIOS currently stores paper-trading broker secret keys in DynamoDB so the
## onboarding flow can work without paid Secrets Manager setup. This is only
## acceptable for private paper-trading development. Before public launch or
## live-money trading, move the active functions in this file back to AWS
## Secrets Manager or another encrypted secret store.

import re

from backend.memory.dynamodb_store import get_item, put_item, utc_now_text


## Normalize user and broker names into a storage-key-safe fragment.
## Cognito subjects can contain characters that are awkward in keys, so this keeps DynamoDB pointers predictable.
def _safe_secret_part(value):
    return re.sub(r"[^A-Za-z0-9/_+=.@-]", "-", str(value))


## Build the stable secret storage partition key for one user's broker credentials.
## Keeping broker secrets under a separate partition makes them easier to migrate to Secrets Manager later.
def broker_secret_pk(user_id):
    return f"USER_SECRET#{_safe_secret_part(user_id)}"


## Build the stable secret storage sort key for one broker.
## The current prototype only supports Alpaca, but this shape keeps future broker support straightforward.
def broker_secret_sk(broker):
    return f"BROKER#{_safe_secret_part(str(broker).lower())}"


## Create or update the DynamoDB record containing the broker secret key.
## TODO before production/live trading: replace this temporary DynamoDB storage with Secrets Manager/KMS-backed storage.
def save_broker_secret(user_id, broker, secret_key):
    pk = broker_secret_pk(user_id)
    sk = broker_secret_sk(broker)
    now = utc_now_text()
    put_item({
        "pk": pk,
        "sk": sk,
        "item_type": "temporary_broker_secret",
        "storage": "dynamodb_prototype",
        "broker": broker,
        "secret_key": secret_key,
        "created_or_updated_at": now,
        "updated_at": now,
    })
    return f"dynamodb://{pk}/{sk}"


## Read the broker secret key for backend-only broker client construction.
## No API route should return this value to the frontend, even while using temporary DynamoDB storage.
def get_broker_secret(secret_pointer):
    if not str(secret_pointer).startswith("dynamodb://"):
        raise ValueError("Unsupported broker secret pointer. Expected temporary DynamoDB pointer.")

    pointer = str(secret_pointer).removeprefix("dynamodb://")
    pk, sk = pointer.rsplit("/", 1)
    item = get_item(pk, sk)

    if not item or not item.get("secret_key"):
        raise ValueError("Broker secret was not found for this user profile.")

    return item["secret_key"]
