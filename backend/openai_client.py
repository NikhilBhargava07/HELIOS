## Construct and reuse the OpenAI SDK client used by HELIOS reasoning services.
##
## A cached client reuses its HTTP connection pool across CSP reviews and market-take
## jobs within the same Lambda execution environment. This module caches only the
## client configuration; each call still sends fresh evidence and receives a new
## model response.

import os
from functools import lru_cache


## Return the shared OpenAI client, or None when AI access is not configured.
## Importing the SDK lazily keeps deterministic local fallbacks available in minimal test environments.
@lru_cache(maxsize=1)
def get_openai_client():
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None

    try:
        from openai import OpenAI
    except ImportError:
        return None

    return OpenAI(api_key=api_key, timeout=45)
