## Store and retrieve broker secrets in AWS Secrets Manager.
##
## A broker secret key can place trades, so it is kept out of the table that holds
## everything else. Anything able to read HELIOS memory would otherwise also be able
## to read every user's trading credentials, which is a much larger blast radius than
## the data those readers actually need.
##
## Secrets written before this module moved to Secrets Manager are still readable
## through their old pointer, so a profile saved earlier keeps working until it is
## migrated. Nothing new is ever written to the old location.

import re

from backend.memory.dynamodb_store import get_item

SECRET_NAME_PREFIX = "helios/users"
LEGACY_POINTER_PREFIX = "dynamodb://"


## Normalize user and broker names into a storage-key-safe fragment.
## Cognito subjects can contain characters that are awkward in a secret name or a table key.
def _safe_secret_part(value):
    return re.sub(r"[^A-Za-z0-9/_+=.@-]", "-", str(value))


## Build the stable Secrets Manager name holding one user's secret for one broker.
## The shape matches the IAM policy that scopes this Lambda to helios/users/* and nothing else.
def broker_secret_name(user_id, broker):
    return f"{SECRET_NAME_PREFIX}/{_safe_secret_part(user_id)}/{_safe_secret_part(str(broker).lower())}"


## Build the partition key of a secret stored before the move to Secrets Manager.
## Kept only so an existing profile can still be read and migrated.
def legacy_broker_secret_pk(user_id):
    return f"USER_SECRET#{_safe_secret_part(user_id)}"


## Build the sort key of a secret stored before the move to Secrets Manager.
def legacy_broker_secret_sk(broker):
    return f"BROKER#{_safe_secret_part(str(broker).lower())}"


## Return the Secrets Manager client, imported lazily so tests and local tools need no AWS session.
def _secrets_client():
    import boto3

    return boto3.client("secretsmanager")


## Write one user's broker secret and return the pointer stored on their profile.
##
## The secret is created on first connection and updated on reconnection, because a
## name that already exists cannot be created again. The returned ARN is what the
## profile keeps; the secret value itself never goes back to the caller.
def save_broker_secret(user_id, broker, secret_key):
    client = _secrets_client()
    name = broker_secret_name(user_id, broker)

    try:
        response = client.create_secret(
            Name=name,
            SecretString=secret_key,
            Description="HELIOS broker secret key for one user and broker.",
        )
        return response["ARN"]
    except client.exceptions.ResourceExistsException:
        response = client.put_secret_value(SecretId=name, SecretString=secret_key)
        return response["ARN"]


## Read one user's broker secret for backend-only broker client construction.
##
## Both pointer shapes are accepted: an ARN or name in Secrets Manager, and the old
## dynamodb:// pointer written before the move. No API route may return this value.
def get_broker_secret(secret_pointer):
    pointer = str(secret_pointer)

    if pointer.startswith(LEGACY_POINTER_PREFIX):
        return _legacy_secret(pointer)

    secret = _secrets_client().get_secret_value(SecretId=pointer).get("SecretString")
    if not secret:
        raise ValueError("Broker secret was not found for this user profile.")

    return secret


## Read a secret still stored under its pre-migration pointer.
## Separated so the path that has to disappear is obvious and easy to delete.
def _legacy_secret(pointer):
    pk, sk = pointer.removeprefix(LEGACY_POINTER_PREFIX).rsplit("/", 1)
    item = get_item(pk, sk)

    if not item or not item.get("secret_key"):
        raise ValueError("Broker secret was not found for this user profile.")

    return item["secret_key"]
