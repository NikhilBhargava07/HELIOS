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


## Build the stable future Secrets Manager name for one user's broker credentials.
## This helper is still useful when we migrate from DynamoDB temporary storage to Secrets Manager.
def broker_secret_name(user_id, broker):
    safe_user_id = _safe_secret_part(user_id)
    safe_broker = _safe_secret_part(broker.lower())
    return f"helios/users/{safe_user_id}/brokers/{safe_broker}"


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


## FUTURE SECRETS MANAGER IMPLEMENTATION
## Keep this block as migration reference. Do not uncomment until AWS Secrets
## Manager is enabled and Lambda's execution role has secretsmanager permissions.
##
## from functools import lru_cache
## from botocore.exceptions import ClientError
##
##
## @lru_cache(maxsize=1)
## def get_secrets_client():
##     import boto3
##
##     return boto3.client("secretsmanager")
##
##
## def save_broker_secret_with_secrets_manager(user_id, broker, secret_key):
##     client = get_secrets_client()
##     secret_name = broker_secret_name(user_id, broker)
##     payload = json.dumps({"broker": broker, "secret_key": secret_key})
##
##     try:
##         response = client.create_secret(Name=secret_name, SecretString=payload)
##         return response["ARN"]
##     except ClientError as error:
##         if error.response.get("Error", {}).get("Code") != "ResourceExistsException":
##             raise
##
##     client.put_secret_value(SecretId=secret_name, SecretString=payload)
##     description = client.describe_secret(SecretId=secret_name)
##     return description["ARN"]
##
##
## def get_broker_secret_with_secrets_manager(secret_arn):
##     response = get_secrets_client().get_secret_value(SecretId=secret_arn)
##     payload = json.loads(response["SecretString"])
##     return payload["secret_key"]
