## Review hard-filtered candidates with OpenAI, or fall back to deterministic rules.
##
## Nothing here knows which strategy is being reviewed. The response shape is the
## same for every strategy, so this module owns the request, the schema, the
## error classification, and the fallback wiring, while the strategy supplies its
## own prompt, its own candidate summary, and its own local review.

import json
import logging
import time

from backend.config import OPENAI_MODEL, OPENAI_REASONING_EFFORT
from backend.openai_client import (
    classify_openai_error,
    get_openai_client,
    openai_error_message,
)


logger = logging.getLogger(__name__)


REVIEW_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "decision": {
            "type": "string",
            "enum": ["approve", "reject_all", "needs_review"],
        },
        "selected_contract": {
            "type": ["string", "null"],
        },
        "summary": {
            "type": "string",
        },
        "risk_note": {
            "type": "string",
        },
        "candidate_reviews": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "contract_symbol": {"type": "string"},
                    "verdict": {
                        "type": "string",
                        "enum": ["approve", "needs_review", "reject"],
                    },
                    "market_context": {"type": "string"},
                    "trade_rationale": {"type": "string"},
                    "key_risk": {"type": "string"},
                },
                "required": [
                    "contract_symbol", "verdict", "market_context",
                    "trade_rationale", "key_risk",
                ],
            },
        },
    },
    "required": [
        "decision", "selected_contract", "summary", "risk_note",
        "candidate_reviews",
    ],
}


## Return the strategy's deterministic review, explaining why the model was not used.
## The interface shows this note so a rule-based result is never mistaken for an AI judgment.
def _fallback_review(strategy, ticker_symbol, candidates, error_code, explanation):
    review = strategy.review.local_review(ticker_symbol, candidates)
    review["ai_error_code"] = error_code
    review["risk_note"] = f"{explanation} " + review["risk_note"]

    return review


## Ask OpenAI to choose, reject, or flag the supplied candidates.
## If the model is unavailable, return the strategy's deterministic fallback in the same response shape.
def review_candidates(
    strategy,
    ticker_symbol,
    candidates,
    market_context=None,
    portfolio_context=None,
    memory_context=None,
):
    review_config = strategy.review
    client = get_openai_client()
    if client is None:
        return _fallback_review(
            strategy,
            ticker_symbol,
            candidates,
            "not_configured",
            "OpenAI access is not configured, so local rule-based review was used.",
        )

    prompt = review_config.build_prompt(
        ticker_symbol,
        candidates,
        strategy.strategy_rules,
        market_context,
        portfolio_context,
        memory_context,
    )

    started_at = time.monotonic()
    try:
        response = client.responses.create(
            model=OPENAI_MODEL,
            input=[
                {
                    "role": "system",
                    "content": review_config.agent_description,
                },
                {
                    "role": "user",
                    "content": prompt,
                },
            ],
            text={
                "format": {
                    "type": "json_schema",
                    "name": review_config.schema_name,
                    "schema": REVIEW_SCHEMA,
                    "strict": True,
                }
            },
            reasoning={"effort": OPENAI_REASONING_EFFORT},
            max_output_tokens=review_config.max_output_tokens,
            prompt_cache_key=review_config.cache_key,
            store=False,
        )
        review = json.loads(response.output_text)
        review["review_source"] = "openai"
        review["ai_error_code"] = None
        logger.info(
            "OpenAI %s review completed in %.2fs (prompt_chars=%s, response_id=%s)",
            strategy.key,
            time.monotonic() - started_at,
            len(prompt),
            getattr(response, "id", None),
        )
        return review
    except Exception as error:
        error_code = classify_openai_error(error)
        logger.warning(
            "OpenAI %s review failed in %.2fs: %s/%s (status=%s, prompt_chars=%s)",
            strategy.key,
            time.monotonic() - started_at,
            error_code,
            type(error).__name__,
            getattr(error, "status_code", None),
            len(prompt),
        )
        return _fallback_review(
            strategy,
            ticker_symbol,
            candidates,
            error_code,
            f"{openai_error_message(error_code)}, so local rule-based review was used.",
        )
