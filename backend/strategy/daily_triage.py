## Review every strategy's best candidates together, three times a trading day.
##
## The interactive path asks the model one question about one strategy, in depth. This
## path asks a different question: across everything HELIOS could do for this account
## right now, what deserves attention? Answering that needs one model call that sees
## all of it, because nothing can rank a put against a covered call against a stock
## without holding them side by side.
##
## It is also why this is cheaper. The market, news, memory, and portfolio evidence is
## the bulk of a prompt, and sending it once per slot rather than once per strategy is
## most of the saving. The per-strategy prompts are left exactly as they are: depth on
## one trade is their job, and triage is this one's.

import json
import logging
import time

from backend.config import (
    OPENAI_MODEL,
    OPENAI_REASONING_EFFORT,
    OPENAI_REVIEW_MAX_OUTPUT_TOKENS,
)
from backend.market.context import build_candidate_review_context
from backend.market.prompt_context import (
    compact_market_context,
    compact_portfolio_context,
)
from backend.memory.learning_user import build_memory_context
from backend.openai_client import (
    classify_openai_error,
    get_openai_client,
    openai_error_message,
)
from backend.strategy.recommender import rank_strategy_candidates
from backend.strategy.registry import STRATEGIES

logger = logging.getLogger(__name__)

# Each strategy offers its best few; the model then picks across all of them.
CANDIDATES_PER_STRATEGY = 3
MAX_PICKS = 3

TRIAGE_AGENT_DESCRIPTION = (
    "You are a cautious trade triage agent for an educational paper-trading prototype. "
    "You compare what a portfolio could do right now and report only what deserves attention."
)

TRIAGE_SCHEMA_NAME = "daily_triage"
TRIAGE_CACHE_KEY = "helios-daily-triage-v1"

TRIAGE_GUIDANCE = """You are HELIOS's daily triage. HELIOS scans on its own three times a trading day, and the
user may read this hours after you write it. Your job is to say what deserves their attention
now, not to analyse one trade in depth.

Every candidate below already passed its strategy's hard rules, and those rules are not yours
to revisit: delta bands, implied volatility limits, spread and liquidity floors, the requirement
that a covered call's strike sits at or above what the shares really cost, and the cash and
exposure limits. Anything you can see has already satisfied them.

The three kinds of candidate commit different things, and that difference matters more than
their headline numbers:
- A cash-secured put commits cash and the obligation to buy 100 shares at the strike. The
  premium is payment for accepting that obligation.
- A covered call commits shares the user already owns, caps their upside at the strike, and
  may end the position by having the shares called away.
- A stock is advisory only. HELIOS will not place it, and the user has to act themselves.
  Say so whenever you recommend one.

Rank by what improves this account today, not by what pays the most. A put paying more than
another is not better if the account is already concentrated in that name or short of the cash
to secure it. A covered call collecting premium is not better than doing nothing if those shares
are the user's strongest long-term holding. Weigh every candidate against what the portfolio
already holds, what is already committed, and what the supplied market and news evidence
actually supports.

Choose at most three, ranked. Choosing fewer is correct when fewer deserve attention, and
choosing none is correct when nothing does. A daily list that always contains three picks
teaches the user to ignore it.

For each pick, say what it is, why it stands out today, and the single risk that matters most.
Then say what would change your view: the observation that would make this a bad idea by the
time the user reads it. The price will have moved before they act, and they need to know what
to check.

Use could and may rather than certainty. Explain terms a beginner would not know. Give more
weight to established reporting than to a single unrated headline, do not invent news, and say
when the evidence is thin rather than filling the gap with generic market commentary.
"""

TRIAGE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "market_read": {"type": "string"},
        "picks": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "strategy_key": {
                        "type": "string",
                        "enum": ["cash_secured_put", "covered_call", "equity"],
                    },
                    "identifier": {"type": "string"},
                    "headline": {"type": "string"},
                    "why_now": {"type": "string"},
                    "key_risk": {"type": "string"},
                    "what_would_change_it": {"type": "string"},
                },
                "required": [
                    "strategy_key", "identifier", "headline",
                    "why_now", "key_risk", "what_would_change_it",
                ],
            },
        },
        "passed_over": {"type": "string"},
    },
    "required": ["market_read", "picks", "passed_over"],
}


## Gather each strategy's best few candidates for one account.
##
## A strategy that cannot offer anything right now is not an error: no cash, no
## uncovered shares, or nothing passing the filters are all ordinary answers, and the
## reason is kept so the triage can say why a whole trade type is missing today.
def collect_candidates(scan_inputs):
    offered = {}
    skipped = {}

    for key, strategy in STRATEGIES.items():
        candidates, rejection = rank_strategy_candidates(
            strategy,
            limit=CANDIDATES_PER_STRATEGY,
            **scan_inputs,
        )
        if rejection:
            skipped[key] = rejection["review"]["summary"]
            continue

        offered[key] = candidates

    return offered, skipped


## Describe one strategy's candidates the way that strategy already describes them.
## Reusing each strategy's own summary keeps one definition of what matters about its trades.
def _summarize(strategy, candidates):
    return [
        strategy.review.summarize_candidate(candidate)
        for candidate in candidates.itertuples()
    ]


## Build the single prompt that compares every strategy's candidates at once.
##
## The stable wording leads so repeated slots and users share a cached prefix, and the
## evidence that changes every run follows it. Earlier picks from the same day are
## included so a later slot can say what changed instead of repeating itself.
def build_triage_prompt(offered, skipped, market_context, portfolio_context, memory_context, earlier_picks=None):
    candidates = {
        key: _summarize(STRATEGIES[key], frame)
        for key, frame in offered.items()
    }
    sections = [
        TRIAGE_GUIDANCE,
        f"Current portfolio and capital context:\n{json.dumps(compact_portfolio_context(portfolio_context or {}), separators=(',', ':'))}",
        f"Retrieved long-term memory:\n{json.dumps(memory_context or {}, separators=(',', ':'))}",
        f"Candidates by strategy, each already ranked best first:\n{json.dumps(candidates, indent=2, default=str)}",
    ]

    if skipped:
        sections.append(
            "Strategies offering nothing right now, and why:\n"
            + json.dumps(skipped, indent=2)
        )

    if earlier_picks:
        sections.append(
            "You already reported these earlier today. Say what has changed rather than repeating "
            "an unchanged idea, and drop one that no longer deserves the space:\n"
            + json.dumps(earlier_picks, indent=2, default=str)
        )

    sections.append(
        f"Market trends, company news, and earnings evidence:\n"
        f"{json.dumps(compact_market_context(market_context or {}), separators=(',', ':'))}"
    )
    sections.append("Return JSON only.")

    return "\n\n".join(sections)


## Report that triage could not run, in the same shape a successful run returns.
## The page can then say why the day is empty instead of rendering nothing at all.
def _empty_triage(reason, error_code=None):
    return {
        "market_read": reason,
        "picks": [],
        "passed_over": "",
        "review_source": "local_fallback",
        "ai_error_code": error_code,
    }


## Ask the model which of today's candidates deserve the user's attention.
##
## There is no deterministic fallback here on purpose. Ranking a put against a stock is
## a judgment, not a calculation, and inventing one without the model would be an
## opinion HELIOS cannot support. Without a model the day simply reports nothing.
def review_daily_candidates(offered, skipped, market_context, portfolio_context, memory_context, earlier_picks=None):
    if not offered:
        return _empty_triage("No strategy could offer a candidate at this scan.")

    client = get_openai_client()
    if client is None:
        return _empty_triage("Automatic review is not configured, so no picks were chosen.", "not_configured")

    prompt = build_triage_prompt(
        offered, skipped, market_context, portfolio_context, memory_context, earlier_picks,
    )
    started_at = time.monotonic()

    try:
        response = client.responses.create(
            model=OPENAI_MODEL,
            input=[
                {"role": "system", "content": TRIAGE_AGENT_DESCRIPTION},
                {"role": "user", "content": prompt},
            ],
            text={"format": {"type": "json_schema", "name": TRIAGE_SCHEMA_NAME,
                             "schema": TRIAGE_SCHEMA, "strict": True}},
            reasoning={"effort": OPENAI_REASONING_EFFORT},
            max_output_tokens=OPENAI_REVIEW_MAX_OUTPUT_TOKENS,
            prompt_cache_key=TRIAGE_CACHE_KEY,
            store=False,
        )

        if getattr(response, "status", None) == "incomplete":
            reason = getattr(getattr(response, "incomplete_details", None), "reason", "unknown")
            logger.warning("Daily triage was cut off after %.2fs (reason=%s)", time.monotonic() - started_at, reason)
            return _empty_triage("The automatic review ran past its output budget.", "incomplete_response")

        triage = json.loads(response.output_text)
        triage["picks"] = triage.get("picks", [])[:MAX_PICKS]
        triage["review_source"] = "openai"
        triage["ai_error_code"] = None
        usage = getattr(response, "usage", None)
        logger.info(
            "Daily triage completed in %.2fs (%s picks, input_tokens=%s, cached_tokens=%s)",
            time.monotonic() - started_at,
            len(triage["picks"]),
            getattr(usage, "input_tokens", None),
            getattr(getattr(usage, "input_tokens_details", None), "cached_tokens", None),
        )
        return triage
    except Exception as error:
        error_code = classify_openai_error(error)
        logger.warning("Daily triage failed in %.2fs: %s", time.monotonic() - started_at, error_code)
        return _empty_triage(openai_error_message(error_code), error_code)


## Build the market evidence once for every ticker any strategy offered.
## Fetching it per strategy would repeat the most expensive part of the scan three times.
def build_shared_market_context(offered, stock_data_client):
    tickers = []
    for frame in offered.values():
        tickers.extend(frame["tickerSymbol"].drop_duplicates().tolist())

    return build_candidate_review_context(list(dict.fromkeys(tickers)), stock_data_client=stock_data_client)


## Run one slot's triage for one account, from broker state to chosen picks.
## Memory failures degrade the review rather than ending the scan, matching the interactive path.
def run_daily_triage(user_id, scan_inputs, stock_data_client, earlier_picks=None):
    offered, skipped = collect_candidates(scan_inputs)
    if not offered:
        return {**_empty_triage("Nothing qualified for any strategy at this scan."), "skipped": skipped, "offered": {}}

    market_context = build_shared_market_context(offered, stock_data_client)
    candidate_tickers = list(dict.fromkeys(
        ticker for frame in offered.values() for ticker in frame["tickerSymbol"]
    ))

    try:
        memory_context = build_memory_context(user_id, candidate_tickers)
    except Exception as error:
        logger.warning("Memory retrieval failed during triage: %s", type(error).__name__)
        memory_context = {"memory_error": "Long-term memory unavailable."}

    triage = review_daily_candidates(
        offered,
        skipped,
        market_context,
        scan_inputs.get("portfolio_context"),
        memory_context,
        earlier_picks,
    )
    triage["skipped"] = skipped
    triage["offered"] = offered

    return triage
