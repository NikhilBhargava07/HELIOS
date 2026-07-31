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
