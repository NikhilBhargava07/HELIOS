"""Review hard-filtered CSP candidates with OpenAI or a local fallback."""

import os
import json

from dotenv import load_dotenv

from backend.config import PROJECT_ROOT


HIGH_ROC_WARNING_PERCENT = 2.00

load_dotenv(PROJECT_ROOT / ".env")

OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.5")


CSP_REVIEW_SCHEMA = {
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
    },
    "required": ["decision", "selected_contract", "summary", "risk_note"],
}


def build_candidate_summary(candidate):
    """Convert one DataFrame candidate row into compact AI input."""
    return {
        "ticker_symbol": candidate.tickerSymbol,
        "contract_symbol": candidate.contractSymbol,
        "expiration": candidate.expiration,
        "dte": int(candidate.DTE),
        "strike": float(candidate.strike),
        "current_stock_price": float(candidate.currentStockPrice),
        "delta": float(candidate.delta),
        "iv_percent": float(candidate.ivPercent),
        "spread": float(candidate.spread),
        "premium": float(candidate.premiumIfSoldAtBid),
        "cash_required": float(candidate.cashRequired),
        "breakeven_price": float(candidate.breakevenPrice),
        "return_on_cash_percent": float(candidate.returnOnCashPercent),
    }


def prepare_candidates_for_ai(candidates):
    """Convert all filtered candidates into JSON-friendly AI input."""
    return [
        build_candidate_summary(candidate)
        for candidate in candidates.itertuples()
    ]


def local_review_csp_candidates(ticker_symbol, candidates):
    """
    Temporary rule-based review until an LLM API key is configured.
    This keeps the ai_review structure usable before OpenAI integration.
    """
    if candidates.empty:
        return {
            "decision": "reject_all",
            "selected_contract": None,
            "summary": "No candidates passed the hard CSP filters.",
            "risk_note": "Try another approved ticker or loosen filters only after understanding the tradeoff.",
        }

    best_candidate = candidates.iloc[0]
    risk_notes = []

    if best_candidate["returnOnCashPercent"] >= HIGH_ROC_WARNING_PERCENT:
        risk_notes.append(
            "ROC is elevated, so inspect news, earnings, and downside risk before selling."
        )

    if best_candidate["ivPercent"] >= 50:
        risk_notes.append(
            "IV is high, which improves premium but may signal a larger expected move."
        )

    if not risk_notes:
        risk_notes.append("Primary risk is assignment if the stock falls below the strike.")

    ticker_display = best_candidate["tickerSymbol"] if "tickerSymbol" in best_candidate else ticker_symbol

    return {
        "decision": "approve",
        "selected_contract": best_candidate["contractSymbol"],
        "summary": (
            f"The top candidate is a {ticker_display} CSP with the best current balance of "
            "target delta, premium, spread, and breakeven among the filtered choices."
        ),
        "risk_note": " ".join(risk_notes),
    }


def build_ai_prompt(ticker_symbol, candidates, strategy_rules):
    """Build instructions that prevent the model from overriding hard rules."""
    candidate_summaries = prepare_candidates_for_ai(candidates)

    return f"""
You are reviewing cash-secured put candidates for an educational paper-trading prototype.

Important rules:
- The candidates already passed hard-coded filters.
- You may approve, reject all, or mark needs_review.
- You may not suggest contracts outside the provided candidates.
- You may not override the strategy rules.
- This is not financial advice and no order will be placed.
- Be concise and practical for a beginner learning CSPs.

Ticker:
{ticker_symbol}

Strategy rules:
{json.dumps(strategy_rules, indent=2)}

Candidate CSPs:
{json.dumps(candidate_summaries, indent=2)}

Return JSON only.
"""


def openai_review_csp_candidates(ticker_symbol, candidates, strategy_rules):
    """Request a schema-validated CSP review from OpenAI."""
    try:
        from openai import OpenAI
    except ImportError:
        review = local_review_csp_candidates(ticker_symbol, candidates)
        review["risk_note"] = (
            "OpenAI SDK is not installed yet, so local rule-based review was used. "
            + review["risk_note"]
        )
        return review

    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    prompt = build_ai_prompt(ticker_symbol, candidates, strategy_rules)

    try:
        response = client.responses.create(
            model=OPENAI_MODEL,
            input=[
                {
                    "role": "system",
                    "content": (
                        "You are a cautious CSP review agent. "
                        "Review only the provided candidates and return structured JSON."
                    ),
                },
                {
                    "role": "user",
                    "content": prompt,
                },
            ],
            text={
                "format": {
                    "type": "json_schema",
                    "name": "csp_review",
                    "schema": CSP_REVIEW_SCHEMA,
                    "strict": True,
                }
            },
        )

        return json.loads(response.output_text)
    except Exception as error:
        review = local_review_csp_candidates(ticker_symbol, candidates)
        review["risk_note"] = (
            f"OpenAI review failed, so local rule-based review was used. "
            f"Error: {error}. "
            + review["risk_note"]
        )
        return review


def review_csp_candidates(ticker_symbol, candidates, strategy_rules):
    """
    Future OpenAI integration point.

    The LLM should only review candidates that already passed hard rules.
    It can rank, explain, or veto, but it should never override filters.
    """
    if not os.getenv("OPENAI_API_KEY"):
        return local_review_csp_candidates(ticker_symbol, candidates)

    return openai_review_csp_candidates(ticker_symbol, candidates, strategy_rules)
