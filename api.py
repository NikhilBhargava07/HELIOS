"""Uvicorn entry point exposing the configured FastAPI application."""

from backend.api.app import app

__all__ = ["app"]
