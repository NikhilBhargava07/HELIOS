## AWS Lambda adapter for the HELIOS FastAPI backend.
##
## API Gateway requests run through Mangum/FastAPI. Internal async worker
## invocations run direct job handlers so long AI calls avoid API Gateway timeout.

from mangum import Mangum

from backend.api.app import app
from backend.market.ai_take_jobs import run_market_take_job

api_handler = Mangum(app, lifespan="off")


## Decide whether a Lambda invocation is a normal HTTP request or an internal background job.
## API Gateway requests are forwarded into FastAPI through Mangum, while market-take worker events run directly so the UI can poll for long OpenAI responses instead of waiting on one request.
def handler(event, context):
    if event.get("worker_action") == "market_take":
        return run_market_take_job(event["job_id"])

    return api_handler(event, context)
