## Store and retrieve broker secrets from AWS Secrets Manager.
##
## HELIOS keeps broker secret keys out of DynamoDB and out of the frontend.
## DynamoDB stores the profile metadata and the secret ARN; Secrets Manager
## stores the sensitive credential material that backend broker clients need.

import json
import re
from functools import lru_cache

from botocore.exceptions import ClientError


## Return a cached Secrets Manager client.
## Reusing one client avoids recreating AWS SDK objects on every Lambda invocation.
@lru_cache(maxsize=1)
def get_secrets_client():
    import boto3

    return boto3.client("secretsmanager")


## Normalize user and broker names into a Secrets Manager path-safe fragment.
## Cognito subjects can contain characters that are awkward in secret names, so this keeps names predictable.
def _safe_secret_part(value):
    return re.sub(r"[^A-Za-z0-9/_+=.@-]", "-", str(value))


## Build the stable Secrets Manager name for one user's broker credentials.
## The path shape makes cleanup and IAM scoping easier later: helios/users/{user}/brokers/{broker}.
def broker_secret_name(user_id, broker):
    safe_user_id = _safe_secret_part(user_id)
    safe_broker = _safe_secret_part(broker.lower())
    return f"helios/users/{safe_user_id}/brokers/{safe_broker}"


## Create or update the Secrets Manager record containing the broker secret key.
## API keys may be visible in profile, but secret keys are write-only from the user's perspective.
def save_broker_secret(user_id, broker, secret_key):
    client = get_secrets_client()
    secret_name = broker_secret_name(user_id, broker)
    payload = json.dumps({"broker": broker, "secret_key": secret_key})

    try:
        response = client.create_secret(Name=secret_name, SecretString=payload)
        return response["ARN"]
    except ClientError as error:
        if error.response.get("Error", {}).get("Code") != "ResourceExistsException":
            raise

    client.put_secret_value(SecretId=secret_name, SecretString=payload)
    description = client.describe_secret(SecretId=secret_name)
    return description["ARN"]


## Read the broker secret key for backend-only broker client construction.
## No API route should return this value to the frontend.
def get_broker_secret(secret_arn):
    response = get_secrets_client().get_secret_value(SecretId=secret_arn)
    payload = json.loads(response["SecretString"])
    return payload["secret_key"]
