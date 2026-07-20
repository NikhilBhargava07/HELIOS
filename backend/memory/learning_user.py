## Build episodic, outcome, and user-profile memory for one user.

from backend.config import MIN_PATTERN_SAMPLE_SIZE
from backend.memory.dynamodb_store import query_items, user_pk
from backend.memory.observations import get_recent_outcome_snapshots
from backend.memory.recommendations import (
    find_candidate,
    get_recommendation_run,
)


## Return recent recommendation-decision episodes related to the requested tickers.
## Each episode joins the saved candidate, agent reasoning, market context, and the user's actual action.
def get_relevant_episodes(user_id, ticker_symbols, limit=8):
    symbols = set(ticker_symbols or [])
    if not symbols:
        return []

    decisions = [
        item
        for item in query_items(
            user_pk(user_id),
            "DECISION#",
            limit=limit * 4,
            scan_forward=False,
        )
        if item.get("ticker_symbol") in symbols
    ]
    episodes = []
    for decision in decisions[:limit]:
        run = get_recommendation_run(
            user_id,
            decision["recommendation_run_id"],
        )
        candidate = (
            find_candidate(run, decision["contract_symbol"])
            if run
            else None
        )
        episodes.append({
            "recommendation_run_id": decision["recommendation_run_id"],
            "recommended_at": run.get("created_at") if run else None,
            "ticker_symbol": decision["ticker_symbol"],
            "contract_symbol": decision["contract_symbol"],
            "candidate": candidate,
            "agent_review": (run or {}).get("agent_review"),
            "market_context": (run or {}).get("market_context"),
            "user_decision": {
                "action": decision.get("action"),
                "note": decision.get("note") or "",
                "decided_at": decision.get("created_at"),
            },
        })
    return episodes


## Count the tickers most often selected by the user.
## This is descriptive evidence only and does not override affordability or strategy rules.
def _top_selected_tickers(placed, limit=5):
    counts = {}
    for item in placed:
        ticker = item.get("ticker_symbol")
        if ticker:
            counts[ticker] = counts.get(ticker, 0) + 1
    return [
        {"value": ticker, "count": count}
        for ticker, count in sorted(
            counts.items(),
            key=lambda pair: pair[1],
            reverse=True,
        )[:limit]
    ]


## Summarize observed decisions and completed outcomes for one user.
## Confidence remains insufficient until the configured evidence threshold is reached.
def build_user_profile(user_id):
    owner_partition = user_pk(user_id)
    decisions = query_items(
        owner_partition,
        "DECISION#",
        limit=200,
        scan_forward=False,
    )
    outcomes = query_items(
        owner_partition,
        "OUTCOME#",
        limit=200,
        scan_forward=False,
    )
    placed = [
        item
        for item in decisions
        if item.get("action") == "place_paper_order"
    ]
    discarded = [
        item
        for item in decisions
        if item.get("action") == "discard"
    ]
    completed_outcomes = [
        item
        for item in outcomes
        if item.get("status") == "complete"
    ]
    assigned_outcomes = [
        item
        for item in completed_outcomes
        if item.get("assigned") is True
    ]
    evidence_count = len(decisions)
    confidence = (
        "insufficient"
        if evidence_count < MIN_PATTERN_SAMPLE_SIZE
        else "low"
    )
    assignment_rate = (
        len(assigned_outcomes) / len(completed_outcomes)
        if completed_outcomes
        else None
    )
    return {
        "profile": {
            "profile_type": "observed_and_inferred",
            "evidence": {
                "total_decisions": evidence_count,
                "placed_orders": len(placed),
                "discarded_candidates": len(discarded),
                "completed_trade_outcomes": len(completed_outcomes),
            },
            "observed_preferences": {
                "most_selected_tickers": _top_selected_tickers(placed),
                "inferred_risk_preference": {
                    "label": "unknown",
                    "evidence_count": len(placed),
                    "confidence": confidence,
                },
            },
            "outcome_preferences": {
                "assignment_rate": assignment_rate,
                "average_premium_retained_percent": None,
                "assignment_tolerance": "unknown",
            },
            "interpretation_limits": (
                "Evidence remains descriptive and must not override "
                "hard strategy or capital rules."
            ),
        },
        "evidence_count": evidence_count,
        "confidence": confidence,
    }


## Aggregate repeated outcome lessons using distinct contracts as samples.
## Multiple daily snapshots of one contract remain longitudinal evidence rather than being miscounted as independent trades.
def get_outcome_patterns(
    user_id,
    ticker_symbols=None,
    minimum_sample_size=MIN_PATTERN_SAMPLE_SIZE,
):
    symbols = set(ticker_symbols or [])
    snapshots = get_recent_outcome_snapshots(user_id, limit=100)
    if symbols:
        snapshots = [
            item
            for item in snapshots
            if item.get("snapshot", {}).get("ticker_symbol") in symbols
        ]

    latest_by_contract = {}
    for item in snapshots:
        contract_symbol = item.get("snapshot", {}).get("contract_symbol")
        if contract_symbol and contract_symbol not in latest_by_contract:
            latest_by_contract[contract_symbol] = item

    grouped = {}
    for item in latest_by_contract.values():
        snapshot = item.get("snapshot", {})
        key = (
            snapshot.get("ticker_symbol"),
            snapshot.get("lesson_type"),
            snapshot.get("financial_status"),
        )
        if not key[0]:
            continue
        pattern = grouped.setdefault(key, {
            "ticker_symbol": key[0],
            "lesson_type": key[1],
            "financial_status": key[2],
            "sample_size": 0,
            "latest_summary": item.get("summary"),
        })
        pattern["sample_size"] += 1

    recent_lessons = [
        {
            "ticker_symbol": item.get("snapshot", {}).get("ticker_symbol"),
            "contract_symbol": item.get("snapshot", {}).get("contract_symbol"),
            "financial_status": item.get("snapshot", {}).get("financial_status"),
            "assignment_status": item.get("snapshot", {}).get("assignment_status"),
            "lesson_type": item.get("snapshot", {}).get("lesson_type"),
            "summary": item.get("summary"),
            "observed_at": item.get("observed_at"),
        }
        for item in snapshots[:10]
    ]
    return {
        "patterns": [
            pattern
            for pattern in grouped.values()
            if pattern["sample_size"] >= minimum_sample_size
        ],
        "recent_lessons": recent_lessons,
        "minimum_sample_size": minimum_sample_size,
        "note": (
            "Recent lessons are directional evidence; repeated patterns "
            "require distinct contracts."
        ),
    }


## Build the complete memory package supplied to recommendation and market-take prompts.
## This is a read-only operation; viewing a page no longer creates redundant profile-version writes.
def build_memory_context(user_id, ticker_symbols):
    return {
        "relevant_episodes": get_relevant_episodes(
            user_id,
            ticker_symbols,
        ),
        "outcome_patterns": get_outcome_patterns(
            user_id,
            ticker_symbols,
        ),
        "recent_outcome_snapshots": get_recent_outcome_snapshots(
            user_id,
            limit=8,
        ),
        "user_profile": build_user_profile(user_id),
        "memory_policy": {
            "minimum_pattern_sample_size": MIN_PATTERN_SAMPLE_SIZE,
            "unselected_candidates_are_counterfactual": True,
            "sparse_preferences_must_not_override_hard_rules": True,
            "backend": "dynamodb",
        },
    }
