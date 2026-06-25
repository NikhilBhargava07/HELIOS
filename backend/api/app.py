## Assemble the FastAPI application, middleware, routes, and static frontend.

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.api.routes.market import router as market_router
from backend.api.routes.memory import router as memory_router
from backend.api.routes.portfolio import router as portfolio_router
from backend.api.routes.recommendations import router as recommendation_router
from backend.config import PROJECT_ROOT


## Build and configure the HELIOS FastAPI application.
def create_app():
    application = FastAPI(title="HELIOS API")
    allowed_origins = [
        origin.strip()
        for origin in os.getenv(
            "CORS_ALLOWED_ORIGINS",
            "http://127.0.0.1:8000,http://localhost:8000",
        ).split(",")
        if origin.strip()
    ]
    application.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )
    application.include_router(portfolio_router)
    application.include_router(recommendation_router)
    application.include_router(market_router)
    application.include_router(memory_router)

    frontend_path = PROJECT_ROOT / "frontend"
    if frontend_path.exists():
        application.mount("/", StaticFiles(directory=frontend_path, html=True), name="frontend")
    return application


app = create_app()
