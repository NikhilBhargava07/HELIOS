## Produce a portfolio-aware market take with OpenAI or a local fallback.

import json
import logging
import time

from backend.config import (
    OPENAI_MARKET_TAKE_MAX_OUTPUT_TOKENS,
    OPENAI_MODEL,
    OPENAI_REASONING_EFFORT,
    SHARES_PER_CONTRACT,
)
from backend.market.prompt_context import compact_market_take_context
from backend.openai_client import (
    classify_openai_error,
    get_openai_client,
    openai_error_message,
)


logger = logging.getLogger(__name__)


MARKET_TAKE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "headline": {"type": "string"},
        "market_mood": {
            "type": "string",
            "enum": ["Calm", "Mixed", "Choppy", "Risky"],
        },
        "csp_stance": {
            "type": "string",
            "enum": ["Favorable", "Selective", "Cautious", "Wait"],
        },
        "reasoned_take": {"type": "string"},
        "csp_take": {"type": "string"},
        "covered_call_take": {"type": "string"},
        "stock_take": {"type": "string"},
        "portfolio_take": {"type": "string"},
        "recommendation_take": {"type": "string"},
        "action": {"type": "string"},
        "avoid": {"type": "string"},
        "company_notes": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "ticker": {"type": "string"},
                    "note": {"type": "string"},
                },
                "required": ["ticker", "note"],
            },
        },
        "scenarios": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
    "required": [
        "headline",
        "market_mood",
        "csp_stance",
        "reasoned_take",
        "csp_take",
        "covered_call_take",
        "stock_take",
        "portfolio_take",
        "recommendation_take",
        "action",
        "avoid",
        "company_notes",
        "scenarios",
    ],
}


## Produce a deterministic fallback market take when OpenAI is unavailable.
## The UI still receives a useful explanation of the whole account instead of failing completely during API outages.
def local_market_take(context):
    trends = context.get("trends") or []
    news = context.get("news") or context.get("news_and_earnings") or []
    if not trends and not news:
        return {
            "headline": "No market context yet.", "market_mood": "Mixed",
            "csp_stance": "Wait",
            "reasoned_take": "Load trends and news before leaning on the market take.",
            "csp_take": "Use only the hard CSP filters for now.",
            "covered_call_take": "Covered calls cannot be judged without market context.",
            "stock_take": "Shares held cannot be judged without market context.",
            "portfolio_take": "Current positions cannot be evaluated without market context.",
            "recommendation_take": "Recent recommendations cannot be compared without market context.",
            "action": "Review filtered CSP candidates normally.",
            "avoid": "Do not force a trade without context.",
            "company_notes": [],
            "scenarios": ["Neutral: continue reviewing filtered CSP candidates only."],
            "review_source": "local_fallback",
        }

    strongest = _rank_trends(trends, reverse=True)
    weakest = _rank_trends(trends, reverse=False)
    portfolio = context.get("portfolio") or {}
    positions = portfolio.get("open_csp_positions") or []
    covered_calls = portfolio.get("covered_call_positions") or []
    holdings = portfolio.get("holdings") or {}
    candidates = (context.get("latest_recommendation") or {}).get("candidates", [])
    position_tickers = [
        position.get("ticker_symbol")
        for position in positions
        if position.get("ticker_symbol")
    ]
    candidate_tickers = list(dict.fromkeys(
        candidate.get("tickerSymbol")
        for candidate in candidates[:4]
        if candidate.get("tickerSymbol")
    ))
    if trends:
        reasoned_take = (
            f"Recent strength includes {', '.join(row['ticker'] for row in strongest)}, while "
            f"{', '.join(row['ticker'] for row in weakest)} look weaker on the 5-day view. "
            "Prefer filtered names with downside cushion that you would accept owning."
        )
        scenarios = [
            f"Stronger 5-day names: {', '.join(row['ticker'] for row in strongest)}.",
            f"Weaker 5-day names: {', '.join(row['ticker'] for row in weakest)}.",
            "Scenario context, not a price prediction.",
        ]
    else:
        reasoned_take = (
            "Recent news is available, but usable trend rows are not. "
            "Treat this fallback as limited context and rely on the hard CSP filters until trend data loads."
        )
        scenarios = [
            "Trend data unavailable: avoid ranking tickers by recent momentum.",
            "News context may identify risks but cannot establish price direction alone.",
            "Scenario context, not a price prediction.",
        ]

    covered_call_tickers = [
        position.get("ticker_symbol")
        for position in covered_calls
        if position.get("ticker_symbol")
    ]
    uncovered_tickers = [
        ticker for ticker, holding in sorted(holdings.items())
        if (holding.get("uncovered_shares") or 0) >= SHARES_PER_CONTRACT
    ]
    share_tickers = sorted(holdings)

    return {
        "headline": "Use trend data as a risk check.",
        "market_mood": "Mixed",
        "csp_stance": "Selective",
        "reasoned_take": reasoned_take,
        "csp_take": "Favor CSPs only when hard filters pass.",
        "covered_call_take": _describe_covered_calls(covered_call_tickers, uncovered_tickers),
        "stock_take": (
            f"Shares held: {', '.join(share_tickers)}. Check concentration before adding to any of them."
            if share_tickers else "No shares are currently held."
        ),
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
        "scenarios": scenarios,
        "review_source": "local_fallback",
    }


## State plainly what the call side of the account looks like when the model is unavailable.
## Shares with no call sold against them are named because that is the next step of a wheel, not a judgment about it.
def _describe_covered_calls(covered_call_tickers, uncovered_tickers):
    if covered_call_tickers:
        sentence = f"Calls are sold against {', '.join(covered_call_tickers)}."
    else:
        sentence = "No covered calls are currently open."

    if uncovered_tickers:
        return f"{sentence} Shares free to cover a call: {', '.join(uncovered_tickers)}."

    return sentence


## Sort trend records by their recent five-day return.
## The fallback calls this in both directions to identify the strongest and weakest tickers.
def _rank_trends(trends, reverse):
    missing_value = -999 if reverse else 999
    return sorted(
        trends,
        key=lambda row: row.get("5d") if row.get("5d") is not None else missing_value,
        reverse=reverse,
    )[:3]


## Ask OpenAI for a portfolio-aware market take, falling back locally on failure.
## This is the main reasoning entry point for the AI Market Take tab.
def ai_market_take(context):
    client = get_openai_client()
    if client is None:
        take = local_market_take(context)
        take["ai_error_code"] = "not_configured"
        return take

    prompt = _build_market_take_prompt(context)
    started_at = time.monotonic()
    try:
        response = client.responses.create(
            model=OPENAI_MODEL,
            input=[
                {"role": "system", "content": "You are a cautious market-context assistant for CSP paper trading."},
                {"role": "user", "content": prompt},
            ],
            text={
                "format": {
                    "type": "json_schema",
                    "name": "market_take",
                    "schema": MARKET_TAKE_SCHEMA,
                    "strict": True,
                }
            },
            reasoning={"effort": OPENAI_REASONING_EFFORT},
            max_output_tokens=OPENAI_MARKET_TAKE_MAX_OUTPUT_TOKENS,
            prompt_cache_key="helios-market-take-v1",
            store=False,
        )
        take = _normalize_market_take(json.loads(response.output_text))
        take["review_source"] = "openai"
        take["ai_error_code"] = None
        logger.info(
            "OpenAI market take completed in %.2fs (prompt_chars=%s, response_id=%s)",
            time.monotonic() - started_at,
            len(prompt),
            getattr(response, "id", None),
        )
        return take
    except Exception as error:
        error_code = classify_openai_error(error)
        logger.warning(
            "OpenAI market take failed in %.2fs: %s/%s (status=%s, prompt_chars=%s)",
            time.monotonic() - started_at,
            error_code,
            type(error).__name__,
            getattr(error, "status_code", None),
            len(prompt),
        )
        fallback = local_market_take(context)
        fallback["ai_error_code"] = error_code
        fallback["reasoned_take"] = (
            f"{openai_error_message(error_code)}, so the local market summary was used."
        )
        return fallback


## Build the prompt that tells the LLM what evidence to use and what JSON to return.
## It includes trends, reputable news, open CSPs, latest recommendations, and memory context without exposing secrets.
def _build_market_take_prompt(context):
    compacted_context = compact_market_take_context(context)
    return f"""
You are helping with an educational paper-trading dashboard that sells cash-secured puts and
covered calls, and gives an opinion on stocks worth owning without ever trading them.
Do not pretend to know the future. Return only valid JSON with these keys:
- headline: max 8 words
- market_mood: one of Calm, Mixed, Choppy, Risky
- csp_stance: one of Favorable, Selective, Cautious, Wait
- reasoned_take: 5 to 7 plain-language sentences on the market overall, using specific trends and news with their sources
- csp_take: 1 to 3 sentences about selling cash-secured puts in these conditions
- covered_call_take: 1 to 3 sentences about any open covered calls and any shares with no call sold against them
- stock_take: 1 to 3 sentences about the shares currently held, their concentration, and whether holding, adding, or trimming reads better
- portfolio_take: 2 to 4 sentences on the account as a whole: total exposure, how the positions interact, and what is committed versus free
- recommendation_take: 2 to 4 sentences comparing the latest recommended tickers
- action: 1-3 sentences, max 50 words, stating whether to monitor, consider a candidate, or pass
- avoid: max 50 words
- company_notes: 2 to 4 objects with ticker and note, prioritizing positions and recommendations
- scenarios: exactly 3 strings, each max 25 words

Read the whole account, not only the puts. The portfolio context names each kind of position
separately: open_csp_positions are short puts backed by cash, covered_call_positions are calls
sold against shares already owned, and share_positions are the stock itself. The holdings map
gives what those shares really cost after any put premium collected when they were assigned,
which is the number that decides whether being called away locks in a gain or a loss.

Treat these as one account rather than separate hobbies. Shares assigned from a put become the
stock position and then the basis for a covered call, so say where each holding sits in that
cycle. A short call caps the upside of the shares beneath it. Cash committed to puts is not
available for anything else. Where a section has nothing in it, say so plainly in one short
sentence instead of inventing activity.

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
{json.dumps(compacted_context, separators=(",", ":"))}
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
        "covered_call_take": take.get("covered_call_take", ""),
        "stock_take": take.get("stock_take", ""),
        "portfolio_take": take.get("portfolio_take", ""),
        "recommendation_take": take.get("recommendation_take", ""),
        "action": take.get("action", ""), "avoid": take.get("avoid", ""),
        "company_notes": take.get("company_notes", [])[:4],
        "scenarios": take.get("scenarios", [])[:3],
    }
