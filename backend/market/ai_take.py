"""Produce a portfolio-aware market take with OpenAI or a local fallback."""

import json
import os
import re

from dotenv import load_dotenv

from backend.config import PROJECT_ROOT

load_dotenv(PROJECT_ROOT / ".env")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.5")


def local_market_take(context):
    """Create a deterministic market summary when OpenAI is unavailable."""
    if not context["trends"] and not context["news"]:
        return {
            "headline": "No market context yet.", "market_mood": "Neutral",
            "csp_stance": "Wait",
            "reasoned_take": "Load trends and news before leaning on the market take.",
            "csp_take": "Use only the hard CSP filters for now.",
            "portfolio_take": "Current positions cannot be evaluated without market context.",
            "recommendation_take": "Recent recommendations cannot be compared without market context.",
            "action": "Review filtered CSP candidates normally.",
            "avoid": "Do not force a trade without context.",
            "company_notes": [],
            "scenarios": ["Neutral: continue reviewing filtered CSP candidates only."],
        }

    strongest = _rank_trends(context["trends"], reverse=True)
    weakest = _rank_trends(context["trends"], reverse=False)
    positions = context.get("portfolio", {}).get("open_csp_positions", [])
    candidates = (context.get("latest_recommendation") or {}).get("candidates", [])
    position_tickers = [position["ticker_symbol"] for position in positions]
    candidate_tickers = list(dict.fromkeys(candidate["tickerSymbol"] for candidate in candidates[:4]))

    return {
        "headline": "Use trend data as a risk check.",
        "market_mood": "Mixed",
        "csp_stance": "Selective",
        "reasoned_take": (
            f"Recent strength includes {', '.join(row['ticker'] for row in strongest)}, while "
            f"{', '.join(row['ticker'] for row in weakest)} look weaker on the 5-day view. "
            "Prefer filtered names with downside cushion that you would accept owning."
        ),
        "csp_take": "Favor CSPs only when hard filters pass.",
        "portfolio_take": (
            f"Current open CSPs: {', '.join(position_tickers)}. Review their assignment risk before adding exposure."
            if position_tickers else "There are no current Alpaca CSP positions to assess."
        ),
        "recommendation_take": (
            f"Latest candidates include {', '.join(candidate_tickers)}. Compare them with existing exposure before placing another CSP."
            if candidate_tickers else "Run recommendations before comparing specific new CSP candidates."
        ),
        "action": "Prefer names you are comfortable owning.",
        "avoid": "Avoid chasing high IV after sharp moves.",
        "company_notes": [
            {"ticker": row["ticker"], "note": "Stronger 5-day trend; still inspect downside risk."}
            for row in strongest
        ],
        "scenarios": [
            f"Stronger 5-day names: {', '.join(row['ticker'] for row in strongest)}.",
            f"Weaker 5-day names: {', '.join(row['ticker'] for row in weakest)}.",
            "Scenario context, not a price prediction.",
        ],
    }


def _rank_trends(trends, reverse):
    """Return the three strongest or weakest rows by five-day movement."""
    missing_value = -999 if reverse else 999
    return sorted(
        trends,
        key=lambda row: row.get("5d") if row.get("5d") is not None else missing_value,
        reverse=reverse,
    )[:3]


def parse_market_take_json(text):
    """Parse JSON even when a model wraps it in Markdown fences or prose."""
    cleaned = re.sub(r"^```(?:json)?", "", text.strip())
    cleaned = re.sub(r"```$", "", cleaned).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if not match:
            raise
        return json.loads(match.group(0))


def ai_market_take(context):
    """Ask OpenAI for a cautious take centered on positions and candidates."""
    if not os.getenv("OPENAI_API_KEY"):
        return local_market_take(context)
    try:
        from openai import OpenAI
    except ImportError:
        return local_market_take(context)

    prompt = _build_market_take_prompt(context)
    try:
        response = OpenAI(api_key=os.getenv("OPENAI_API_KEY")).responses.create(
            model=OPENAI_MODEL,
            input=[
                {"role": "system", "content": "You are a cautious market-context assistant for CSP paper trading."},
                {"role": "user", "content": prompt},
            ],
        )
        take = parse_market_take_json(response.output_text)
        return _normalize_market_take(take)
    except Exception as error:
        fallback = local_market_take(context)
        fallback["reasoned_take"] = f"AI failed, so local fallback was used: {error}"
        return fallback


def _build_market_take_prompt(context):
    """Build instructions that prevent generic or unsupported market claims."""
    return f"""
You are helping with an educational cash-secured put paper-trading dashboard.
Do not pretend to know the future. Return only valid JSON with these keys:
- headline: max 8 words
- market_mood: one of Calm, Mixed, Choppy, Risky
- csp_stance: one of Favorable, Selective, Cautious, Wait
- reasoned_take: 3 to 5 plain-language sentences using specific trends and news
- csp_take: 1 to 2 sentences about CSP paper trading
- portfolio_take: 2 to 4 sentences about every current CSP position and assignment risk
- recommendation_take: 2 to 4 sentences comparing the latest recommended tickers
- action: max 24 words stating whether to monitor, consider a candidate, or pass
- avoid: max 24 words
- company_notes: 2 to 4 objects with ticker and note, prioritizing positions and recommendations
- scenarios: exactly 3 strings, each max 20 words

The portfolio and latest recommendations are the center of the response. Explain difficult terms,
use could/may rather than certainty, connect relevant news to named companies, and do not invent
user patterns that are absent from the context.

Context:
{json.dumps(context, indent=2)}
"""


def _normalize_market_take(take):
    """Return a stable response shape even if optional model fields are absent."""
    return {
        "headline": take.get("headline", "Market risk check"),
        "market_mood": take.get("market_mood", "Mixed"),
        "csp_stance": take.get("csp_stance", "Selective"),
        "reasoned_take": take.get("reasoned_take", take.get("summary", "")),
        "csp_take": take.get("csp_take", ""),
        "portfolio_take": take.get("portfolio_take", ""),
        "recommendation_take": take.get("recommendation_take", ""),
        "action": take.get("action", ""), "avoid": take.get("avoid", ""),
        "company_notes": take.get("company_notes", [])[:4],
        "scenarios": take.get("scenarios", [])[:3],
    }
