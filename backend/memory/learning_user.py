## Builds evidence-backed episodic, outcome, and user-profile memory.

import hashlib
import json
from collections import Counter, defaultdict
from statistics import mean
from uuid import uuid4

from psycopg.types.json import Jsonb

from backend.memory.database import ensure_schema, get_connection, json_safe, utc_now


## Convert nullable database numbers to floats.
def _number(value):
    return None if value is None else float(value)


## Label how much evidence supports a derived memory.
def _confidence(evidence_count):
    if evidence_count < 5:
        return "insufficient"
    if evidence_count < 20:
        return "low"
    if evidence_count < 50:
        return "medium"
    return "high"


## Average one numeric candidate field when observations exist.
def _average(rows, key):
    values = [_number(row.get(key)) for row in rows if row.get(key) is not None]
    return round(mean(values), 4) if values else None


## Return the observed minimum and maximum for one selected feature.
def _range(rows, key):
    values = [_number(row.get(key)) for row in rows if row.get(key) is not None]
    return None if not values else {"min": min(values), "max": max(values)}


## Return the most frequently observed categorical values.
def _top_counts(rows, key, limit=5):
    counts = Counter(row.get(key) for row in rows if row.get(key))
    return [{"value": value, "count": count} for value, count in counts.most_common(limit)]


## Derive a transparent preference profile from decisions and outcomes.
def build_user_profile():
    ensure_schema()
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT d.*, c.dte, c.delta, c.iv_percent, c.return_on_cash_percent,
                       c.cash_required, c.strike, t.status AS outcome_status,
                       t.outcome_label, t.assigned, t.premium_retained_percent
                FROM user_decisions d
                LEFT JOIN csp_candidates c
                  ON c.recommendation_run_id = d.recommendation_run_id
                 AND c.contract_symbol = d.contract_symbol
                LEFT JOIN trade_outcomes t ON t.decision_id = d.id
                ORDER BY d.created_at ASC
                """
            )
            decisions = cursor.fetchall()

    placed = [row for row in decisions if row["action"] == "place_paper_order"]
    discarded = [row for row in decisions if row["action"] == "discard"]
    completed = [row for row in placed if row.get("outcome_status") == "complete"]
    assigned = [row for row in completed if row.get("assigned")]
    agreed = [
        row for row in placed
        if row.get("agent_selected_contract") == row.get("contract_symbol")
    ]

    profile = {
        "profile_type": "observed_and_inferred",
        "evidence": {
            "total_decisions": len(decisions),
            "placed_orders": len(placed),
            "discarded_candidates": len(discarded),
            "completed_trade_outcomes": len(completed),
        },
        "observed_preferences": {
            "most_selected_tickers": _top_counts(placed, "ticker_symbol"),
            "average_selected_delta": _average(placed, "delta"),
            "selected_delta_range": _range(placed, "delta"),
            "average_selected_iv_percent": _average(placed, "iv_percent"),
            "selected_iv_percent_range": _range(placed, "iv_percent"),
            "average_selected_dte": _average(placed, "dte"),
            "selected_dte_range": _range(placed, "dte"),
            "average_selected_roc_percent": _average(placed, "return_on_cash_percent"),
            "average_selected_cash_required": _average(placed, "cash_required"),
            "agent_selection_agreement_rate": (
                round(len(agreed) / len(placed), 4) if placed else None
            ),
            "inferred_risk_preference": _infer_risk_preference(placed),
        },
        "outcome_preferences": {
            "assignment_rate": (
                round(len(assigned) / len(completed), 4) if completed else None
            ),
            "average_premium_retained_percent": _average(
                completed, "premium_retained_percent"
            ),
            "assignment_tolerance": "unknown" if not completed else (
                "observed" if assigned else "not_yet_observed"
            ),
        },
        "recent_user_notes": [
            row["note"] for row in reversed(decisions)
            if row.get("note")
        ][:5],
        "interpretation_limits": (
            "Preferences are descriptive, not causal. Sparse evidence must not override "
            "capital limits or hard strategy rules."
        ),
    }
    evidence_count = len(decisions)
    return {
        "profile": profile,
        "evidence_count": evidence_count,
        "confidence": _confidence(evidence_count),
    }


## Infer a coarse risk preference only after repeated selections.
def _infer_risk_preference(placed):
    if len(placed) < 5:
        return {"label": "unknown", "evidence_count": len(placed), "confidence": "insufficient"}
    average_delta = abs(_average(placed, "delta") or 0)
    average_iv = _average(placed, "iv_percent") or 0
    if average_delta <= 0.23 and average_iv < 40:
        label = "more_conservative_within_strategy"
    elif average_delta >= 0.27 or average_iv >= 55:
        label = "more_aggressive_within_strategy"
    else:
        label = "moderate_within_strategy"
    return {
        "label": label,
        "evidence_count": len(placed),
        "confidence": _confidence(len(placed)),
    }


## Persist a profile only when its evidence-backed contents changed.
def save_user_profile_version(profile_result):
    ensure_schema()
    canonical = json.dumps(profile_result["profile"], sort_keys=True, separators=(",", ":"))
    fingerprint = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    profile_id = str(uuid4())
    generated_at = utc_now()
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO user_profile_versions (
                    id, generated_at, evidence_count, confidence, profile, fingerprint
                ) VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (fingerprint) DO NOTHING
                """,
                (
                    profile_id, generated_at, profile_result["evidence_count"],
                    profile_result["confidence"], Jsonb(profile_result["profile"]),
                    fingerprint,
                ),
            )
            cursor.execute(
                "SELECT * FROM user_profile_versions WHERE fingerprint = %s",
                (fingerprint,),
            )
            row = cursor.fetchone()
    return json_safe(row)


## Keep only ticker-relevant evidence from a historical context snapshot.
def _compact_market_context(context, ticker_symbol):
    context = context or {}
    trends = [
        trend for trend in context.get("trends", [])
        if trend.get("ticker") in {ticker_symbol, "SPY", "QQQ", "IWM"}
    ]
    news = [
        item for item in context.get("news_and_earnings", [])
        if ticker_symbol in item.get("symbols", [])
    ][:3]
    return {"trends": trends, "news_and_earnings": news}


## Keep overall and contract-specific reasoning without unrelated candidates.
def _compact_agent_review(review, contract_symbol):
    review = review or {}
    candidate_review = next(
        (
            item for item in review.get("candidate_reviews", [])
            if item.get("contract_symbol") == contract_symbol
        ),
        None,
    )
    return {
        "decision": review.get("decision"),
        "selected_contract": review.get("selected_contract"),
        "summary": review.get("summary"),
        "risk_note": review.get("risk_note"),
        "candidate_review": candidate_review,
    }


## Retrieve recent decisions and outcomes involving candidate tickers.
def get_relevant_episodes(ticker_symbols, limit=8):
    ensure_schema()
    symbols = list(dict.fromkeys(ticker_symbols))
    if not symbols:
        return []
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT r.id AS run_id, r.created_at AS recommended_at,
                       r.agent_review, r.market_context, r.strategy_rules,
                       c.raw_candidate, c.ticker_symbol, c.contract_symbol,
                       d.id AS decision_id, d.action, d.note, d.created_at AS decided_at,
                       p.status AS order_status, p.alpaca_order_id,
                       t.status AS outcome_status, t.outcome_label, t.realized_pnl,
                       t.premium_retained_percent, t.assigned, t.expired_worthless
                FROM csp_candidates c
                JOIN recommendation_runs r ON r.id = c.recommendation_run_id
                LEFT JOIN user_decisions d
                  ON d.recommendation_run_id = c.recommendation_run_id
                 AND d.contract_symbol = c.contract_symbol
                LEFT JOIN paper_orders p ON p.decision_id = d.id
                LEFT JOIN trade_outcomes t ON t.decision_id = d.id
                WHERE c.ticker_symbol = ANY(%s)
                ORDER BY COALESCE(d.created_at, r.created_at) DESC
                LIMIT %s
                """,
                (symbols, limit),
            )
            rows = cursor.fetchall()

    episodes = []
    for row in rows:
        episodes.append(json_safe({
            "recommendation_run_id": row["run_id"],
            "recommended_at": row["recommended_at"],
            "ticker_symbol": row["ticker_symbol"],
            "contract_symbol": row["contract_symbol"],
            "candidate": row["raw_candidate"],
            "agent_review": _compact_agent_review(
                row["agent_review"], row["contract_symbol"]
            ),
            "market_context": _compact_market_context(
                row.get("market_context"), row["ticker_symbol"]
            ),
            "user_decision": None if row.get("decision_id") is None else {
                "action": row.get("action"), "note": row.get("note") or "",
                "decided_at": row.get("decided_at"),
            },
            "order_status": row.get("order_status"),
            "outcome": None if row.get("outcome_status") is None else {
                "status": row.get("outcome_status"),
                "label": row.get("outcome_label"),
                "realized_pnl": row.get("realized_pnl"),
                "premium_retained_percent": row.get("premium_retained_percent"),
                "assigned": row.get("assigned"),
                "expired_worthless": row.get("expired_worthless"),
            },
        }))
    return episodes


## Bucket the saved one-month ticker trend for pattern aggregation.
def _trend_bucket(market_context, ticker_symbol):
    for trend in (market_context or {}).get("trends", []):
        if trend.get("ticker") != ticker_symbol or trend.get("1m") is None:
            continue
        one_month = float(trend["1m"])
        if one_month < -2:
            return "down_more_than_2_percent"
        if one_month > 2:
            return "up_more_than_2_percent"
        return "flat_within_2_percent"
    return "trend_unknown"


## Bucket absolute put delta into interpretable strategy ranges.
def _delta_bucket(delta):
    if delta is None:
        return "delta_unknown"
    absolute = abs(float(delta))
    if absolute <= 0.22:
        return "delta_0.20_to_0.22"
    if absolute <= 0.26:
        return "delta_0.23_to_0.26"
    return "delta_0.27_to_0.30"


## Bucket implied volatility for interpretable outcome cohorts.
def _iv_bucket(iv_percent):
    if iv_percent is None:
        return "iv_unknown"
    value = float(iv_percent)
    if value < 35:
        return "iv_20_to_35"
    if value < 50:
        return "iv_35_to_50"
    return "iv_50_to_80"


## Aggregate 30-day candidate observations without overstating small samples.
def get_outcome_patterns(ticker_symbols=None, minimum_sample_size=5):
    ensure_schema()
    symbols = list(dict.fromkeys(ticker_symbols or []))
    where = "AND c.ticker_symbol = ANY(%s)" if symbols else ""
    params = [symbols] if symbols else []
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT o.*, c.delta, c.iv_percent, r.market_context
                FROM candidate_observations o
                JOIN csp_candidates c ON c.id = o.candidate_id
                JOIN recommendation_runs r ON r.id = o.recommendation_run_id
                WHERE o.horizon_days = 30
                  AND o.premium_retained_percent IS NOT NULL
                  {where}
                ORDER BY o.observed_at DESC
                """,
                params,
            )
            rows = cursor.fetchall()

            actual_where = "AND t.ticker_symbol = ANY(%s)" if symbols else ""
            cursor.execute(
                f"""
                SELECT t.premium_retained_percent, t.ticker_symbol,
                       c.delta, c.iv_percent, r.market_context
                FROM trade_outcomes t
                JOIN user_decisions d ON d.id = t.decision_id
                JOIN csp_candidates c
                  ON c.recommendation_run_id = d.recommendation_run_id
                 AND c.contract_symbol = d.contract_symbol
                JOIN recommendation_runs r ON r.id = c.recommendation_run_id
                WHERE t.status = 'complete'
                  AND t.premium_retained_percent IS NOT NULL
                  {actual_where}
                ORDER BY t.updated_at DESC
                """,
                params,
            )
            actual_rows = cursor.fetchall()

    cohorts = defaultdict(list)
    datasets = [
        ("30-day hypothetical candidate observation", rows),
        ("realized trade outcome", actual_rows),
    ]
    for measurement, dataset in datasets:
        for row in dataset:
            keys = [
                ("market_trend", _trend_bucket(row.get("market_context"), row["ticker_symbol"])),
                ("delta", _delta_bucket(row.get("delta"))),
                ("iv", _iv_bucket(row.get("iv_percent"))),
            ]
            for dimension, bucket in keys:
                cohorts[(measurement, dimension, bucket)].append(
                    float(row["premium_retained_percent"])
                )

    patterns = []
    for (measurement, dimension, bucket), values in cohorts.items():
        if len(values) < minimum_sample_size:
            continue
        patterns.append({
            "dimension": dimension,
            "setup": bucket,
            "sample_size": len(values),
            "positive_premium_retention_rate": round(
                sum(value > 0 for value in values) / len(values), 4
            ),
            "average_premium_retained_percent": round(mean(values), 2),
            "confidence": _confidence(len(values)),
            "measurement": measurement,
        })
    return sorted(patterns, key=lambda item: item["sample_size"], reverse=True)[:12]


## Assemble compact memory for one recommendation request.
def build_memory_context(ticker_symbols):
    profile_result = build_user_profile()
    profile_version = save_user_profile_version(profile_result)
    return {
        "relevant_episodes": get_relevant_episodes(ticker_symbols),
        "outcome_patterns": get_outcome_patterns(ticker_symbols),
        "user_profile": profile_version,
        "memory_policy": {
            "minimum_pattern_sample_size": 5,
            "unselected_candidates_are_counterfactual": True,
            "sparse_preferences_must_not_override_hard_rules": True,
        },
    }
