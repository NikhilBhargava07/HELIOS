## AWS Lambda adapter for the HELIOS FastAPI backend.
##
## API Gateway requests run through Mangum/FastAPI. Internal async worker
## invocations run direct job handlers so long AI calls avoid API Gateway timeout.

import logging

from mangum import Mangum

from backend.api.app import app
from backend.market.ai_take_jobs import run_market_take_job

api_handler = Mangum(app, lifespan="off")
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
    if event.get("worker_action") == "market_take":
        return run_market_take_job(
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
