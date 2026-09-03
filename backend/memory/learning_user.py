## Build episodic, outcome, and user-profile memory for one user.

from backend.config import MIN_PATTERN_SAMPLE_SIZE
from backend.memory.dynamodb_store import query_items, user_pk
from backend.memory.feedback import get_trade_feedback
from backend.memory.observations import get_recent_outcome_snapshots
from backend.memory.outcomes import get_completed_trade_outcomes
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
    completed_outcomes = get_completed_trade_outcomes(user_id, limit=100)
    outcomes_by_run_and_contract = {
        (item.get("recommendation_run_id"), item.get("contract_symbol")): item
        for item in completed_outcomes
    }
    feedback_by_run_and_contract = {
        (item.get("recommendation_run_id"), item.get("contract_symbol")): item
        for item in get_trade_feedback(user_id, limit=100)
    }
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
            "completed_outcome": outcomes_by_run_and_contract.get((
                decision.get("recommendation_run_id"),
                decision.get("contract_symbol"),
            )),
            "user_feedback": feedback_by_run_and_contract.get((
                decision.get("recommendation_run_id"),
                decision.get("contract_symbol"),
            )),
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
    outcomes = get_completed_trade_outcomes(user_id, limit=200)
    feedback = get_trade_feedback(user_id, limit=200)
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
    completed_outcomes = outcomes
    assigned_outcomes = [
        item
        for item in completed_outcomes
        if item.get("assigned") is True
    ]
    completed_order_ids = {
        item.get("opening_order_id")
        for item in completed_outcomes
        if item.get("opening_order_id")
    }
    independent_trade_count = max(len(placed), len(completed_order_ids))
    decision_count = len(decisions)
    confidence = (
        "insufficient"
        if independent_trade_count < MIN_PATTERN_SAMPLE_SIZE
        else "low"
    )
    assignment_rate = (
        len(assigned_outcomes) / len(completed_outcomes)
        if completed_outcomes
        else None
    )
    retained_values = [
        item.get("premium_retained_percent")
        for item in completed_outcomes
        if item.get("premium_retained_percent") is not None
    ]
    average_premium_retained = (
        sum(retained_values) / len(retained_values)
        if retained_values
        else None
    )
    realized_pnl_values = [
        item.get("option_realized_pnl")
        for item in completed_outcomes
        if item.get("option_realized_pnl") is not None
    ]
    satisfaction_counts = {}
    reason_counts = {}
    assignment_preference_counts = {}
    for item in feedback:
        satisfaction = item.get("satisfaction")
        if satisfaction:
            satisfaction_counts[satisfaction] = satisfaction_counts.get(satisfaction, 0) + 1
        for reason in item.get("reason_tags") or []:
            reason_counts[reason] = reason_counts.get(reason, 0) + 1
        assignment_preference = item.get("assignment_preference")
        if assignment_preference and assignment_preference != "not_applicable":
            assignment_preference_counts[assignment_preference] = (
                assignment_preference_counts.get(assignment_preference, 0) + 1
            )
    would_repeat_count = sum(1 for item in feedback if item.get("would_repeat") is True)
    explicit_assignment_tolerance = _explicit_assignment_tolerance(
        assignment_preference_counts
    )
    return {
        "profile": {
            "profile_type": "observed_and_inferred",
            "evidence": {
                "total_decisions": decision_count,
                "placed_orders": len(placed),
                "discarded_candidates": len(discarded),
                "completed_trade_outcomes": len(completed_outcomes),
                "independent_trade_count": independent_trade_count,
                "explicit_trade_feedback": len(feedback),
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
                "average_premium_retained_percent": average_premium_retained,
                "total_option_realized_pnl": (
                    sum(realized_pnl_values) if realized_pnl_values else None
                ),
                "assignment_tolerance": explicit_assignment_tolerance,
                "assignment_preference_counts": assignment_preference_counts,
                "would_repeat_rate": (
                    would_repeat_count / len(feedback) if feedback else None
                ),
                "satisfaction_counts": satisfaction_counts,
                "most_common_feedback_reasons": [
                    {"value": reason, "count": count}
                    for reason, count in sorted(
                        reason_counts.items(),
                        key=lambda pair: pair[1],
                        reverse=True,
                    )[:5]
                ],
            },
            "interpretation_limits": (
                "Evidence remains descriptive and must not override "
                "hard strategy or capital rules."
            ),
        },
        "evidence_count": independent_trade_count,
        "independent_trade_count": independent_trade_count,
        "confidence": confidence,
    }


## Translate explicit assignment feedback into a readable preference label.
## User-declared evidence may be used immediately, but a mixed set remains selective rather than being overstated as a fixed preference.
def _explicit_assignment_tolerance(counts):
    total = sum(counts.values())
    if not total:
        return "unknown"
    if counts.get("avoid", 0) / total > 0.5:
        return "prefers_to_avoid"
    if counts.get("welcome", 0) / total > 0.5:
        return "welcomes_assignment"
    return "accepts_selectively"


## Classify a completed option leg by its measurable economic result.
## Assignment stays its own status because the acquired shares' gain or loss is not yet final.
def _completed_financial_status(outcome):
    if outcome.get("assigned"):
        return "assigned_with_stock_outcome_pending"

    option_pnl = outcome.get("option_realized_pnl")
    if option_pnl is None:
        return "unknown"
    if option_pnl > 0:
        return "profitable"
    if option_pnl < 0:
        return "loss"
    return "flat"


## Count one observation toward its ticker, resolution, and result pattern bucket.
## Evidence without a ticker is skipped so unlabeled records cannot inflate a pattern's sample size.
def _count_pattern(grouped, ticker_symbol, lesson_type, financial_status, summary):
    if not ticker_symbol:
        return

    pattern = grouped.setdefault((ticker_symbol, lesson_type, financial_status), {
        "ticker_symbol": ticker_symbol,
        "lesson_type": lesson_type,
        "financial_status": financial_status,
        "sample_size": 0,
        "latest_summary": summary,
    })
    pattern["sample_size"] += 1


## Aggregate repeated outcome lessons using distinct contracts as samples.
## Multiple daily snapshots of one contract remain longitudinal evidence rather than being miscounted as independent trades.
def get_outcome_patterns(
    user_id,
    ticker_symbols=None,
    minimum_sample_size=MIN_PATTERN_SAMPLE_SIZE,
):
    symbols = set(ticker_symbols or [])
    completed_outcomes = get_completed_trade_outcomes(user_id, limit=100)
    snapshots = get_recent_outcome_snapshots(user_id, limit=100)
    if symbols:
        completed_outcomes = [
            item
            for item in completed_outcomes
            if item.get("ticker_symbol") in symbols
        ]
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
    for item in completed_outcomes:
        _count_pattern(
            grouped,
            item.get("ticker_symbol"),
            item.get("resolution_type"),
            _completed_financial_status(item),
            (item.get("outcome_review") or {}).get("summary")
            or item.get("interpretation"),
        )

    completed_contracts = {
        item.get("contract_symbol")
        for item in completed_outcomes
    }
    for item in latest_by_contract.values():
        snapshot = item.get("snapshot", {})
        if snapshot.get("contract_symbol") in completed_contracts:
            continue
        _count_pattern(
            grouped,
            snapshot.get("ticker_symbol"),
            snapshot.get("lesson_type"),
            snapshot.get("financial_status"),
            item.get("summary"),
        )

    completed_lessons = [
        {
            "ticker_symbol": item.get("ticker_symbol"),
            "contract_symbol": item.get("contract_symbol"),
            "financial_status": (
                "assigned_with_stock_outcome_pending"
                if item.get("assigned")
                else "complete"
            ),
            "assignment_status": "assigned" if item.get("assigned") else "not_assigned",
            "lesson_type": item.get("resolution_type"),
            "summary": (
                (item.get("outcome_review") or {}).get("summary")
                or item.get("interpretation")
            ),
            "observed_at": item.get("completed_at"),
            "premium_retained_percent": item.get("premium_retained_percent"),
            "option_realized_pnl": item.get("option_realized_pnl"),
            "outcome_review": item.get("outcome_review"),
        }
        for item in completed_outcomes[:10]
    ]
    open_lessons = [
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
    recent_lessons = sorted(
        [*completed_lessons, *open_lessons],
        key=lambda item: item.get("observed_at") or "",
        reverse=True,
    )[:10]
    return {
        "patterns": [
            pattern
            for pattern in grouped.values()
            if pattern["sample_size"] >= minimum_sample_size
        ],
        "driver_patterns": _outcome_driver_patterns(
            completed_outcomes,
            minimum_sample_size,
        ),
        "recent_lessons": recent_lessons,
        "minimum_sample_size": minimum_sample_size,
        "note": (
            "Recent lessons are directional evidence; repeated patterns "
            "require distinct contracts."
        ),
    }


## Aggregate reviewed causal factors only after distinct contracts repeat them.
## The evidence threshold prevents one dramatic outcome or repeated refreshes from becoming a supposed general rule.
def _outcome_driver_patterns(outcomes, minimum_sample_size):
    grouped = {}
    for outcome in outcomes:
        contract_symbol = outcome.get("contract_symbol")
        for driver in (outcome.get("outcome_review") or {}).get("drivers") or []:
            category = driver.get("category")
            direction = driver.get("direction")
            if not category or not direction or not contract_symbol:
                continue
            key = (category, direction)
            pattern = grouped.setdefault(key, {
                "category": category,
                "direction": direction,
                "contract_symbols": set(),
                "latest_explanation": driver.get("explanation"),
            })
            pattern["contract_symbols"].add(contract_symbol)

    return [
        {
            "category": pattern["category"],
            "direction": pattern["direction"],
            "sample_size": len(pattern["contract_symbols"]),
            "latest_explanation": pattern["latest_explanation"],
        }
        for pattern in grouped.values()
        if len(pattern["contract_symbols"]) >= minimum_sample_size
    ]


## Build the complete memory package supplied to recommendation and market-take prompts.
## This is a read-only operation; viewing a page no longer creates redundant profile-version writes.
def build_memory_context(user_id, ticker_symbols):
    relevant_patterns = get_outcome_patterns(
        user_id,
        ticker_symbols,
    )
    portfolio_patterns = get_outcome_patterns(user_id)
    return {
        "relevant_episodes": get_relevant_episodes(
            user_id,
            ticker_symbols,
        ),
        "outcome_patterns": relevant_patterns,
        "portfolio_outcome_patterns": portfolio_patterns,
        "recent_outcome_snapshots": get_recent_outcome_snapshots(
            user_id,
            limit=8,
        ),
        "user_profile": build_user_profile(user_id),
        "explicit_trade_feedback": get_trade_feedback(user_id, limit=10),
        "memory_policy": {
            "minimum_pattern_sample_size": MIN_PATTERN_SAMPLE_SIZE,
            "unselected_candidates_are_counterfactual": True,
            "sparse_preferences_must_not_override_hard_rules": True,
            "explicit_user_feedback_is_not_the_same_as_financial_outcome": True,
            "backend": "dynamodb",
        },
    }
