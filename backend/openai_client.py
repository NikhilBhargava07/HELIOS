## Construct and reuse the OpenAI SDK client used by HELIOS reasoning services.
##
## A cached client reuses its HTTP connection pool across CSP reviews and market-take
## jobs within the same Lambda execution environment. This module caches only the
## client configuration; each call still sends fresh evidence and receives a new
## model response.

import os
from functools import lru_cache
from pathlib import Path

from backend.config import OPENAI_MAX_RETRIES, OPENAI_TIMEOUT_SECONDS


OPENAI_ERROR_MESSAGES = {
    "authentication_error": "OpenAI authentication failed",
    "rate_limited": "OpenAI temporarily rate-limited the request",
    "timeout": "OpenAI did not respond before the request timeout",
    "connection_error": "HELIOS could not reach OpenAI",
    "service_error": "OpenAI returned a temporary service error",
    "invalid_response": "OpenAI returned an unusable structured response",
    "incomplete_response": "OpenAI's reply was cut off before it finished",
    "request_error": "OpenAI could not complete the request",
}


## Load the local .env file only for OpenAI access during development.
## Lambda receives OPENAI_API_KEY from its own environment and does not package python-dotenv.
def _load_local_openai_environment():
    if os.getenv("AWS_LAMBDA_FUNCTION_NAME"):
        return

    try:
        from dotenv import load_dotenv
    except ImportError:
        return

    project_root = Path(__file__).resolve().parent.parent
    load_dotenv(project_root / ".env")


## Return the shared OpenAI client, or None when AI access is not configured.
## Importing the SDK lazily keeps deterministic local fallbacks available in minimal test environments.
@lru_cache(maxsize=1)
def get_openai_client():
    _load_local_openai_environment()
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None

    try:
        from openai import OpenAI
    except ImportError:
        return None

    return OpenAI(
        api_key=api_key,
        timeout=OPENAI_TIMEOUT_SECONDS,
        max_retries=OPENAI_MAX_RETRIES,
    )


## Convert SDK and JSON failures into a small set of safe diagnostic codes.
## API responses can expose these codes for troubleshooting without leaking prompts, credentials, or provider response bodies.
def classify_openai_error(error):
    status_code = getattr(error, "status_code", None)
    error_name = type(error).__name__.lower()
    if status_code in {401, 403}:
        return "authentication_error"
    if status_code == 429:
        return "rate_limited"
    if status_code is not None and status_code >= 500:
        return "service_error"
    if "timeout" in error_name:
        return "timeout"
    if "connection" in error_name:
        return "connection_error"
    if "json" in error_name or "validation" in error_name:
        return "invalid_response"
    return "request_error"


## Return a beginner-readable explanation for one safe OpenAI diagnostic code.
## Keeping this wording centralized gives CSP review and Market Take consistent fallback messages.
def openai_error_message(error_code):
    return OPENAI_ERROR_MESSAGES.get(
        error_code,
        OPENAI_ERROR_MESSAGES["request_error"],
    )
