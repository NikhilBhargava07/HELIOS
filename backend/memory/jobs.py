## Shared record shape for user-scoped asynchronous jobs.
##
## Recommendation scans, AI market takes, and learning refreshes all create the
## same kind of record: a pending row inside the owner's partition that a worker
## updates and the browser polls. Defining that shape once keeps the three job
## types from drifting apart in status names, TTL handling, or exposed fields.

import time
from uuid import uuid4

from backend.config import AI_JOB_TTL_SECONDS
from backend.memory.dynamodb_store import (
    get_item,
    put_item,
    user_pk,
    utc_now_text,
)


## Create a pending job of one type inside the authenticated user's partition.
## Extra fields record what the worker should do, such as which strategy to scan; the core fields always win, so a caller cannot overwrite status or ownership.
def create_job(user_id, sort_key_prefix, item_type, **fields):
    job_id = str(uuid4())
    now = utc_now_text()
    item = {
        **fields,
        "pk": user_pk(user_id),
        "sk": f"{sort_key_prefix}#{job_id}",
        "item_type": item_type,
        "job_id": job_id,
        "user_id": user_id,
        "status": "pending",
        "created_at": now,
        "updated_at": now,
        "completed_at": None,
        "expires_at": int(time.time()) + AI_JOB_TTL_SECONDS,
        "result": None,
        "error": None,
    }
    put_item(item)
    return public_job(item)


## Read one stored job row only from the requesting user's private partition.
## A job id belonging to another account therefore behaves exactly like a missing record.
def read_job_item(user_id, sort_key_prefix, job_id):
    return get_item(user_pk(user_id), f"{sort_key_prefix}#{job_id}")


## Persist a job status transition while retaining its identity and TTL fields.
## All worker updates pass through this helper so timestamps stay consistent across job types.
def update_job(item, **changes):
    updated = {**item, **changes, "updated_at": utc_now_text()}
    put_item(updated)
    return updated


## Return only the fields a polling frontend needs to render progress or a result.
## DynamoDB partition keys, ownership metadata, and expiration bookkeeping stay private.
def public_job(item):
    return {
        "job_id": item["job_id"],
        "status": item["status"],
        "created_at": item.get("created_at"),
        "updated_at": item.get("updated_at"),
        "completed_at": item.get("completed_at"),
        "result": item.get("result"),
        "error": item.get("error"),
    }
