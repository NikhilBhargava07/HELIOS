## AWS Lambda adapter for the HELIOS FastAPI backend.
##
## Local development still uses `uvicorn api:app`. AWS Lambda uses `handler`,
## which lets API Gateway requests run through the same FastAPI routes.

from mangum import Mangum

from backend.api.app import app


handler = Mangum(app, lifespan="off")
