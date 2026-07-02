## Produce a portfolio-aware market take with OpenAI or a local fallback.

import json
import logging
import os
import re

from backend.config import OPENAI_MODEL


logger = logging.getLogger(__name__)


## Produce a deterministic fallback market take when OpenAI is unavailable.
## The UI still receives a useful CSP-focused explanation instead of failing completely during API outages.
def local_market_take(context):
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


## Sort trend records by recent absolute movement.
## The fallback take uses the most active tickers to describe what the market is doing.
def _rank_trends(trends, reverse):
    missing_value = -999 if reverse else 999
    return sorted(
        trends,
        key=lambda row: row.get("5d") if row.get("5d") is not None else missing_value,
        reverse=reverse,
    )[:3]


## Parse the model response into the structured market-take schema.
## The parser tolerates fenced JSON because LLMs sometimes wrap otherwise valid JSON in markdown.
def parse_market_take_json(text):
    cleaned = re.sub(r"^```(?:json)?", "", text.strip())
    cleaned = re.sub(r"```$", "", cleaned).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if not match:
            raise
        return json.loads(match.group(0))


## Ask OpenAI for a portfolio-aware market take, falling back locally on failure.
## This is the main reasoning entry point for the AI Market Take tab.
def ai_market_take(context):
    if not os.getenv("OPENAI_API_KEY"):
        return local_market_take(context)
    try:
        from openai import OpenAI
    except ImportError:
        return local_market_take(context)

    prompt = _build_market_take_prompt(context)
    try:
        response = OpenAI(api_key=os.getenv("OPENAI_API_KEY"), timeout=45).responses.create(
            model=OPENAI_MODEL,
            input=[
                {"role": "system", "content": "You are a cautious market-context assistant for CSP paper trading."},
                {"role": "user", "content": prompt},
            ],
        )
        take = parse_market_take_json(response.output_text)
        return _normalize_market_take(take)
    except Exception as error:
        logger.warning("OpenAI market take failed: %s", type(error).__name__)
        fallback = local_market_take(context)
        fallback["reasoned_take"] = "AI was unavailable, so the local market summary was used."
        return fallback


## Build the prompt that tells the LLM what evidence to use and what JSON to return.
## It includes trends, reputable news, open CSPs, latest recommendations, and memory context without exposing secrets.
def _build_market_take_prompt(context):
    return f"""
You are helping with an educational cash-secured put paper-trading dashboard.
Do not pretend to know the future. Return only valid JSON with these keys:
- headline: max 8 words
- market_mood: one of Calm, Mixed, Choppy, Risky
- csp_stance: one of Favorable, Selective, Cautious, Wait
- reasoned_take: 5 to 7 plain-language sentences using specific trends and news, along with their sources
- csp_take: 1 to 3 sentences about CSP paper trading
- portfolio_take: 1 to 3 sentences about every current CSP position and assignment risk
- recommendation_take: 2 to 4 sentences comparing the latest recommended tickers
- action: 1-3 sentences, max 50 words, stating whether to monitor, consider a candidate, or pass
- avoid: max 50 words
- company_notes: 2 to 4 objects with ticker and note, prioritizing positions and recommendations
- scenarios: exactly 3 strings, each max 25 words

The portfolio and latest recommendations are the center of the response. Explain difficult terms,
use could/may rather than certainty, connect relevant news to named companies, and do not invent
user patterns that are absent from the context.

Primarily use supplied context. If additional evidence is supplied by the system,
only use evidence from pre-approved or accredited sources such as Reuters, Bloomberg,
WSJ, Financial Times, AP, CNBC, official company releases, earnings reports, or SEC filings.
Do not invent news.

The news list is a curated evidence feed, not a complete market record. Give more weight to
trusted_reporting and established_reporting items, and treat unrated headlines as weaker evidence.
Use article tags and why_it_matters to identify catalysts, especially layoffs, restructuring,
earnings, guidance, AI infrastructure, regulation, macro data, and geopolitical risk. If those
catalysts touch open positions or latest recommended tickers, discuss the actual CSP implication:
premium quality, assignment risk, whether the stock seems stable enough, and whether the user
should wait instead of selling a put. Use the news to also assess whether assignment risk is 
worth higher premiums, as there may be a chance that the stock doesn't recover or rebound for a long time.

Look at relevant geopolitical and political developments only through their plausible economic
and market effects for reference as to what the state of the market is, without pushing a political agenda. 
However, if certain political events are affecting a company or industry, do take that into account when
making your assessment. Avoid generic statements about the market or economy, and do not make predictions.
Trace specific channels such as oil and energy costs, inflation and rates,
currencies, tariffs or sanctions, supply chains, regional revenue, consumer demand, government
spending, and investor risk appetite. Explain why each channel matters to named positions or
recommended tickers, distinguish verified events from scenarios, and avoid political advocacy.
Do not assume that broad instability affects every company in the same direction.
Give greater weight to established reporting and corroborated events. Treat a single unrated,
opinion-based, or speculative headline as weak evidence rather than established market context.

The current source data has already been retrieved for you. Avoid using outdated information or
sources that are not relevant to the current market situation. If the supplied evidence is thin,
say the take is limited rather than filling gaps with generic market commentary.

Context:
{json.dumps(context, indent=2)}
"""


## Fill missing market-take fields so the frontend can render a stable layout.
## This protects the UI from partial model responses while preserving the model’s main reasoning.
def _normalize_market_take(take):
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
