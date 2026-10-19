## Shared DynamoDB primitives for HELIOS memory repositories.
##
## Domain behavior belongs in the focused recommendation, trade, position,
## observation, and learning modules. This file only owns table access, key
## helpers, serialization, and common read/write operations.

import json
import logging
from datetime import date, datetime, timezone
from decimal import Decimal
from functools import lru_cache

from backend.config import DYNAMODB_TABLE_NAME

logger = logging.getLogger(__name__)


## Return the authenticated user's stable DynamoDB partition key.
## Requiring the user id at every domain boundary prevents one Cognito user from reading another user's memory.
def user_pk(user_id):
    if not user_id:
        raise ValueError("A user id is required for user-scoped memory.")
    return f"USER#{user_id}"


## Return a cached DynamoDB table resource.
## Lambda execution environments can reuse this object across warm invocations instead of rebuilding the resource for every request.
@lru_cache(maxsize=1)
def get_table():
    import boto3

    return boto3.resource("dynamodb").Table(DYNAMODB_TABLE_NAME)


## Format the current UTC timestamp as sortable ISO text.
## Recommendation runs, decisions, and observations use this value in sort keys and response metadata.
def utc_now_text():
    return datetime.now(timezone.utc).isoformat()


## Convert Python values into DynamoDB-compatible values.
## Boto3 requires Decimal instead of float and ISO text instead of datetime objects.
def to_dynamodb_value(value):
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, int):
        return value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, list):
        return [to_dynamodb_value(item) for item in value]
    if isinstance(value, dict):
        return {
            key: to_dynamodb_value(item)
            for key, item in value.items()
            if item is not None
        }
    return value


## Convert DynamoDB values back into normal Python values.
## API responses should contain ordinary ints and floats rather than Decimal objects.
def from_dynamodb_value(value):
    if isinstance(value, Decimal):
        return int(value) if value % 1 == 0 else float(value)
    if isinstance(value, list):
        return [from_dynamodb_value(item) for item in value]
    if isinstance(value, dict):
        return {key: from_dynamodb_value(item) for key, item in value.items()}
    return value


## Store one serialized item in the configured DynamoDB table.
## Domain repositories use this for individual records and pointer updates.
# DynamoDB refuses any item over 400KB, and it refuses it at write time with a message that
# names neither the item nor the field responsible. A recommendation run reached that ceiling
# by accumulating retrieved memory over months, so the failure arrived long after the cause.
MAXIMUM_ITEM_BYTES = 400 * 1024
ITEM_SIZE_WARNING_BYTES = 280 * 1024


## Log an item that is approaching DynamoDB's hard size limit, naming its largest fields.
## The point is to see the growth in CloudWatch while it is still only large, not once it fails.
def warn_if_item_is_outgrowing_dynamodb(item):
    try:
        measured = len(json.dumps(item, default=str).encode("utf-8"))
    except Exception:
        return

    if measured < ITEM_SIZE_WARNING_BYTES:
        return

    widest = sorted(
        ((key, len(json.dumps(value, default=str).encode("utf-8"))) for key, value in item.items()),
        key=lambda pair: -pair[1],
    )[:3]
    logger.warning(
        "DynamoDB item is %.0fKB of the %.0fKB limit (%s, %s): %s",
        measured / 1024,
        MAXIMUM_ITEM_BYTES / 1024,
        item.get("item_type", "unknown type"),
        item.get("sk", "unknown key"),
        ", ".join(f"{key}={size / 1024:.0f}KB" for key, size in widest),
    )


def put_item(item):
    warn_if_item_is_outgrowing_dynamodb(item)
    get_table().put_item(Item=to_dynamodb_value(item))


## Store several items with DynamoDB's batch writer.
## Recommendation runs use this to avoid one network round trip per candidate.
def put_items(items):
    with get_table().batch_writer(overwrite_by_pkeys=["pk", "sk"]) as batch:
        for item in items:
            batch.put_item(Item=to_dynamodb_value(item))


## Fetch one item by its complete partition and sort key.
## Missing records return None so repositories can distinguish absence from storage failure.
def get_item(pk, sk):
    response = get_table().get_item(Key={"pk": pk, "sk": sk})
    return from_dynamodb_value(response.get("Item"))


## Query items under one partition key and optional sort-key prefix.
## Callers can request newest-first ordering and a DynamoDB-side result limit without scanning the table.
def query_items(pk, sk_prefix=None, limit=None, scan_forward=True):
    from boto3.dynamodb.conditions import Key

    condition = Key("pk").eq(pk)
    if sk_prefix:
        condition &= Key("sk").begins_with(sk_prefix)

    query = {
        "KeyConditionExpression": condition,
        "ScanIndexForward": scan_forward,
    }
    if limit:
        query["Limit"] = limit

    response = get_table().query(**query)
    return [
        from_dynamodb_value(item)
        for item in response.get("Items", [])
    ]
