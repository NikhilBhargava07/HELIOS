## AWS Lambda adapter for the HELIOS FastAPI backend.
##
## API Gateway requests run through Mangum/FastAPI. Internal async worker
## invocations run direct job handlers so long AI calls avoid API Gateway timeout.

import logging

from mangum import Mangum

from backend.api.app import app
from backend.market.ai_take_jobs import run_market_take_job
from backend.memory.outcome_jobs import (
    dispatch_scheduled_outcome_observations,
    run_outcome_observation,
)
from backend.strategy.recommendation_jobs import run_recommendation_job
from backend.strategy.triage_jobs import dispatch_scheduled_triage, run_triage_slot

api_handler = Mangum(app, lifespan="off")

# Lambda's text log format leaves the root logger at WARNING, which silently dropped every
# informational line HELIOS writes, including scan timings and OpenAI cache measurements.
logging.getLogger().setLevel(logging.INFO)
logger = logging.getLogger(__name__)


## Return only non-sensitive request metadata for logs.
## The body is intentionally omitted because profile/broker requests can contain API keys.
def request_log_context(event):
    request_context = event.get("requestContext") or {}
    http_context = request_context.get("http") or {}
    return {
        "method": http_context.get("method") or event.get("httpMethod"),
        "path": event.get("rawPath") or event.get("path"),
        "route_key": event.get("routeKey"),
    }


## Decide whether a Lambda invocation is a normal HTTP request or an internal background job.
## API Gateway requests are forwarded into FastAPI through Mangum, while market-take worker events run directly so the UI can poll for long OpenAI responses instead of waiting on one request.
def handler(event, context):
    if event.get("worker_action") == "scheduled_outcome_dispatch":
        return dispatch_scheduled_outcome_observations()

    if event.get("worker_action") == "scheduled_triage_dispatch":
        return dispatch_scheduled_triage(event["slot"])

    if event.get("worker_action") == "triage_slot":
        return run_triage_slot(
            event["user_id"],
            event["slot"],
            force=event.get("force", False),
        )

    if event.get("worker_action") == "outcome_observation":
        return run_outcome_observation(
            event["user_id"],
            job_id=event.get("job_id"),
            trigger=event.get("trigger", "on_demand"),
        )

    if event.get("worker_action") == "market_take":
        return run_market_take_job(
            event["job_id"],
            event["user_id"],
        )

    if event.get("worker_action") == "recommendation_scan":
        return run_recommendation_job(
            event["job_id"],
            event["user_id"],
        )

    request_context = request_log_context(event)
    logger.info("HELIOS request start: %s", request_context)
    try:
        response = api_handler(event, context)
    except Exception as error:
        logger.exception("Lambda request crashed before response: %s context=%s", type(error).__name__, request_context)
        raise

    status_code = int(response.get("statusCode") or 0)
    logger.info(
        "HELIOS request end: status=%s context=%s",
        status_code,
        request_context,
    )
    if status_code >= 500:
        logger.error("Lambda returned %s for context=%s", status_code, request_context)

    return response
