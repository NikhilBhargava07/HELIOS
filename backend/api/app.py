## Assemble the FastAPI application, middleware, routes, and static frontend.

import os
import logging

from fastapi import FastAPI
from fastapi import Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.api.routes.market import router as market_router
from backend.api.routes.portfolio import router as portfolio_router
from backend.api.routes.profiles import router as profile_router
from backend.api.routes.recommendations import router as recommendation_router
from backend.config import PROJECT_ROOT

logger = logging.getLogger(__name__)


## Convert unexpected backend crashes into a JSON response while logging the real exception.
## This keeps the browser from seeing only API Gateway's generic "Internal Server Error" and gives CloudWatch enough context to debug.
async def unexpected_error_handler(request: Request, error: Exception):
    logger.exception(
        "Unhandled API error on %s %s: %s",
        request.method,
        request.url.path,
        type(error).__name__,
    )
    return JSONResponse(
        status_code=500,
        content={
            "detail": "Unexpected backend error.",
            "error_code": "unexpected_backend_error",
        },
    )


## Construct the shared FastAPI application used by local Uvicorn and AWS Lambda.
## Lambda serves only API routes, while local development may mount the frontend for one-process testing.
def create_app(serve_frontend=None):
    application = FastAPI(title="HELIOS API")
    application.add_exception_handler(Exception, unexpected_error_handler)
    allowed_origins = [
        origin.strip()
        for origin in os.getenv("CORS_ALLOWED_ORIGINS", "").split(",")
        if origin.strip()
    ]
    if allowed_origins:
        application.add_middleware(
            CORSMiddleware,
            allow_origins=allowed_origins,
            allow_methods=["GET", "POST"],
            allow_headers=["Content-Type", "Authorization"],
        )
    application.include_router(portfolio_router)
    application.include_router(profile_router)
    application.include_router(recommendation_router)
    application.include_router(market_router)

    if serve_frontend is None:
        serve_frontend = not bool(os.getenv("AWS_LAMBDA_FUNCTION_NAME"))
    frontend_path = PROJECT_ROOT / "frontend"
    if serve_frontend and frontend_path.exists():
        application.mount("/", StaticFiles(directory=frontend_path, html=True), name="frontend")
    return application


app = create_app()
