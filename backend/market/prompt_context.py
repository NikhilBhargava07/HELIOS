## Compact market, portfolio, and memory records before sending them to an LLM.
##
## DynamoDB stores complete recommendation evidence for auditing, but repeatedly
## embedding old market contexts inside new prompts creates unnecessary latency.
## These helpers retain decision-relevant facts while removing nested history,
## UI-only fields, URLs, and oversized article summaries.


NEWS_FIELDS = (
    "headline",
    "summary",
    "source",
    "source_quality",
    "created_at",
    "symbols",
    "tags",
    "why_it_matters",
    "category",
)
TREND_FIELDS = (
    "ticker",
    "1d",
    "5d",
    "2w",
    "1m",
    "ytd",
)
CANDIDATE_FIELDS = (
    "tickerSymbol",
    "contractSymbol",
    "expiration",
    "DTE",
    "strike",
    "currentStockPrice",
    "delta",
    "ivPercent",
    "spread",
    "premiumIfSoldAtBid",
    "cashRequired",
    "breakevenPrice",
    "returnOnCashPercent",
)
POSITION_FIELDS = (
    "ticker_symbol",
    "contract_symbol",
    "expiration",
    "strike",
    "quantity",
    "premium_received",
    "cash_required",
    "breakeven_price",
    "market_value",
    "unrealized_pnl",
    "current_price",
    "average_entry_price",
)
OUTCOME_FIELDS = (
    "completed_at",
    "resolution_type",
    "assigned",
    "opening_credit",
    "closing_debit",
    "option_realized_pnl",
    "premium_retained_percent",
    "assignment_cash_obligation",
    "effective_share_cost",
    "underlying_outcome_pending",
    "interpretation",
)


## Truncate long source summaries without altering short evidence fields.
## This limits token usage while keeping enough text to understand the catalyst.
def compact_text(value, maximum_characters=360):
    if not isinstance(value, str) or len(value) <= maximum_characters:
        return value
    return value[:maximum_characters].rsplit(" ", 1)[0] + "..."


## Copy an approved subset of fields from one dictionary.
## Optional text limits are applied only to strings, leaving numeric evidence exact.
def select_fields(record, fields, text_limit=None):
    if not isinstance(record, dict):
        return {}
    selected = {}
    for field in fields:
        if field not in record or record[field] is None:
            continue
        value = record[field]
        selected[field] = compact_text(value, text_limit) if text_limit else value
    return selected


## Reduce trend and news evidence to fields the model can cite and compare.
## Both general-market and candidate-specific context shapes are supported.
def compact_market_context(context, news_limit=24, trend_limit=24):
    context = context or {}
    news_key = "news_and_earnings" if "news_and_earnings" in context else "news"
    compacted = {
        "trends": [
            select_fields(item, TREND_FIELDS)
            for item in (context.get("trends") or [])[:trend_limit]
        ],
        news_key: [
            select_fields(item, NEWS_FIELDS, text_limit=360)
            for item in (context.get(news_key) or [])[:news_limit]
        ],
    }
    for field in (
        "candidate_tickers",
        "news_and_earnings_lookback_days",
        "trends_error",
        "news_error",
    ):
        if field in context and context[field] is not None:
            compacted[field] = context[field]
    return compacted


## Keep account limits and current CSP exposure while omitting repeated UI data.
## The model receives enough information to enforce concentration and cash rules.
def compact_portfolio_context(context):
    context = context or {}
    positions = (
        context.get("open_csp_positions")
        or context.get("open_positions")
        or []
    )
    capital = context.get("capital") or {}
    return {
        "capital": {
            key: value
            for key, value in capital.items()
            if key != "open_positions"
        },
        "open_csp_positions": [
            select_fields(position, POSITION_FIELDS)
            for position in positions
        ],
        "position_source": context.get("position_source"),
    }


## Flatten one historical episode into its candidate, decision, and concise rationale.
## Full prior market contexts are intentionally excluded to prevent recursive prompts.
def compact_episode(episode):
    review = episode.get("agent_review") or {}
    completed_outcome = episode.get("completed_outcome")
    return {
        "recommended_at": episode.get("recommended_at"),
        "ticker_symbol": episode.get("ticker_symbol"),
        "contract_symbol": episode.get("contract_symbol"),
        "candidate": select_fields(
            episode.get("candidate") or {},
            CANDIDATE_FIELDS,
        ),
        "agent_review": {
            "decision": review.get("decision"),
            "selected_contract": review.get("selected_contract"),
            "summary": compact_text(review.get("summary"), 280),
            "risk_note": compact_text(review.get("risk_note"), 240),
        },
        "user_decision": episode.get("user_decision") or {},
        "completed_outcome": (
            select_fields(
                completed_outcome,
                OUTCOME_FIELDS,
                text_limit=280,
            )
            if completed_outcome
            else None
        ),
    }


## Build a bounded long-term-memory excerpt for a new CSP review.
## Recent lessons remain visible, but old raw prompts and duplicated snapshots do not.
def compact_memory_context(context):
    context = context or {}
    outcome_patterns = context.get("outcome_patterns") or {}
    return {
        "relevant_episodes": [
            compact_episode(episode)
            for episode in (context.get("relevant_episodes") or [])[:6]
        ],
        "outcome_patterns": {
            "patterns": (outcome_patterns.get("patterns") or [])[:8],
            "recent_lessons": (outcome_patterns.get("recent_lessons") or [])[:6],
            "minimum_sample_size": outcome_patterns.get("minimum_sample_size"),
            "note": outcome_patterns.get("note"),
        },
        "recent_outcome_snapshots": [
            {
                "observed_at": item.get("observed_at"),
                "summary": compact_text(item.get("summary"), 280),
                "snapshot": item.get("snapshot") or {},
            }
            for item in (context.get("recent_outcome_snapshots") or [])[:6]
        ],
        "user_profile": context.get("user_profile"),
        "memory_policy": context.get("memory_policy") or {},
        "memory_error": context.get("memory_error"),
    }


## Reduce the latest recommendation to the facts needed by AI Market Take.
## Its saved memory and prior market context are excluded because current evidence is supplied separately.
def compact_recommendation_context(recommendation):
    if not recommendation:
        return None
    review = recommendation.get("agent_review") or {}
    return {
        "id": recommendation.get("id"),
        "created_at": recommendation.get("created_at"),
        "candidates": [
            select_fields(candidate, CANDIDATE_FIELDS)
            for candidate in (recommendation.get("candidates") or [])[:6]
        ],
        "agent_review": {
            "decision": review.get("decision"),
            "selected_contract": review.get("selected_contract"),
            "summary": compact_text(review.get("summary"), 320),
            "risk_note": compact_text(review.get("risk_note"), 280),
        },
    }


## Build the complete bounded evidence package used by AI Market Take.
## Fresh market data, current positions, and the latest recommendation remain central.
def compact_market_take_context(context):
    compacted = compact_market_context(context, news_limit=24, trend_limit=24)
    compacted["portfolio"] = compact_portfolio_context(
        context.get("portfolio") or {}
    )
    compacted["latest_recommendation"] = compact_recommendation_context(
        context.get("latest_recommendation")
    )
    return compacted
