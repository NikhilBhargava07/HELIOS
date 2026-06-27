## DynamoDB-backed memory store for Lambda deployment.
##
## The table uses a single-table design with pk/sk keys. Postgres remains the
## default local backend; this module is used when MEMORY_BACKEND=dynamodb.

from datetime import date, datetime, timezone
from decimal import Decimal
from functools import lru_cache
from uuid import uuid4

from backend.config import (
    DYNAMODB_TABLE_NAME,
    MAX_CSP_CAPITAL_PERCENT,
    MAX_OPEN_POSITIONS,
    TOTAL_CAPITAL,
    USER_ID,
)
from backend.memory.serializers import normalize_candidate

USER_PK = f"USER#{USER_ID}"
FILLED_ORDER_STATUSES = {"filled"}


## Return a cached DynamoDB table resource.
@lru_cache(maxsize=1)
def get_table():
    import boto3

    return boto3.resource("dynamodb").Table(DYNAMODB_TABLE_NAME)


## Return a timezone-aware UTC timestamp in DynamoDB-friendly text form.
def utc_now_text():
    return datetime.now(timezone.utc).isoformat()


## Convert Python values into DynamoDB-safe values.
def to_dynamodb_value(value):
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, int):
        return value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, list):
        return [to_dynamodb_value(item) for item in value]
    if isinstance(value, dict):
        return {
            key: to_dynamodb_value(item)
            for key, item in value.items()
            if item is not None
        }
    return value


## Convert DynamoDB Decimals back into API-safe int/float values.
def from_dynamodb_value(value):
    if isinstance(value, Decimal):
        return int(value) if value % 1 == 0 else float(value)
    if isinstance(value, list):
        return [from_dynamodb_value(item) for item in value]
    if isinstance(value, dict):
        return {key: from_dynamodb_value(item) for key, item in value.items()}
    return value


## Store an item after converting unsupported Python numeric/date types.
def put_item(item):
    get_table().put_item(Item=to_dynamodb_value(item))


## Read a single item by primary key.
def get_item(pk, sk):
    response = get_table().get_item(Key={"pk": pk, "sk": sk})
    return from_dynamodb_value(response.get("Item"))


## Query one partition and return API-safe items.
def query_items(pk, sk_prefix=None, limit=None, scan_forward=True):
    from boto3.dynamodb.conditions import Key

    condition = Key("pk").eq(pk)
    if sk_prefix:
        condition = condition & Key("sk").begins_with(sk_prefix)
    kwargs = {
        "KeyConditionExpression": condition,
        "ScanIndexForward": scan_forward,
    }
    if limit:
        kwargs["Limit"] = limit
    response = get_table().query(**kwargs)
    return [from_dynamodb_value(item) for item in response.get("Items", [])]


## Scan a small prototype table for items matching one item type.
def scan_items(item_type, limit=200):
    response = get_table().scan(
        FilterExpression="item_type = :item_type",
        ExpressionAttributeValues={":item_type": item_type},
        Limit=limit,
    )
    return [from_dynamodb_value(item) for item in response.get("Items", [])]


## Find a contract inside a previously saved recommendation run.
def find_candidate(run, contract_symbol):
    return next(
        (candidate for candidate in run["candidates"] if candidate["contractSymbol"] == contract_symbol),
        None,
    )


## Save an AI review and its filtered candidates to DynamoDB.
def save_recommendation_run(
    candidates,
    review,
    market_context=None,
    strategy_rules=None,
    portfolio_context=None,
    memory_context=None,
):
    run_id = str(uuid4())
    created_at = utc_now_text()
    run_pk = f"RUN#{run_id}"
    candidate_records = [normalize_candidate(candidate) for candidate in candidates]
    run_item = {
        "pk": run_pk,
        "sk": "META",
        "item_type": "recommendation_run",
        "id": run_id,
        "created_at": created_at,
        "agent_review": review,
        "market_context": market_context or {},
        "strategy_rules": strategy_rules or {},
        "portfolio_context": portfolio_context or {},
        "memory_context": memory_context or {},
    }
    put_item(run_item)
    put_item({
        "pk": USER_PK,
        "sk": f"RUN#{created_at}#{run_id}",
        "item_type": "run_index",
        "run_id": run_id,
        "created_at": created_at,
    })
    put_item({
        "pk": USER_PK,
        "sk": "LATEST_RUN",
        "item_type": "latest_run_pointer",
        "run_id": run_id,
        "created_at": created_at,
    })
    for candidate in candidate_records:
        put_item({
            "pk": run_pk,
            "sk": f"CANDIDATE#{candidate['contractSymbol']}",
            "item_type": "csp_candidate",
            "id": str(uuid4()),
            "recommendation_run_id": run_id,
            "contract_symbol": candidate["contractSymbol"],
            "ticker_symbol": candidate["tickerSymbol"],
            "created_at": created_at,
            "candidate": candidate,
        })
    return {
        "id": run_id,
        "created_at": created_at,
        "candidates": candidate_records,
        "agent_review": review,
        "market_context": market_context or {},
        "strategy_rules": strategy_rules or {},
        "portfolio_context": portfolio_context or {},
        "memory_context": memory_context or {},
    }


## Load one saved recommendation run and its candidates from DynamoDB.
def get_recommendation_run(run_id):
    run_pk = f"RUN#{run_id}"
    run = get_item(run_pk, "META")
    if not run:
        return None
    candidate_items = query_items(run_pk, "CANDIDATE#")
    candidates = [item["candidate"] for item in candidate_items]
    return {
        "id": run["id"],
        "created_at": run["created_at"],
        "candidates": candidates,
        "agent_review": run.get("agent_review", {}),
        "market_context": run.get("market_context", {}),
        "strategy_rules": run.get("strategy_rules", {}),
        "portfolio_context": run.get("portfolio_context", {}),
        "memory_context": run.get("memory_context", {}),
    }


## Load the latest recommendation run through the user pointer item.
def get_latest_recommendation_run():
    pointer = get_item(USER_PK, "LATEST_RUN")
    return get_recommendation_run(pointer["run_id"]) if pointer else None


## Build the database representation of a submitted Alpaca paper order.
def create_paper_order(decision, candidate, alpaca_order=None):
    alpaca_order = alpaca_order or {}
    return {
        "id": str(uuid4()),
        "created_at": utc_now_text(),
        "decision_id": decision["id"],
        "status": alpaca_order.get("status", "local_recorded"),
        "side": "sell",
        "strategy": "cash-secured put",
        "contract_symbol": candidate["contractSymbol"],
        "ticker_symbol": candidate["tickerSymbol"],
        "expiration": candidate["expiration"],
        "strike": candidate["strike"],
        "premium_received": candidate["premiumIfSoldAtBid"],
        "cash_required": candidate["cashRequired"],
        "breakeven_price": candidate["breakevenPrice"],
        "alpaca_order_id": alpaca_order.get("id"),
        "alpaca_client_order_id": alpaca_order.get("client_order_id"),
        "alpaca_limit_price": alpaca_order.get("limit_price"),
        "alpaca_submitted_at": alpaca_order.get("submitted_at"),
        "raw_alpaca_order": alpaca_order.get("raw_order") or {},
    }


## Build a local open position record when an order is already filled.
def create_open_position(order, candidate):
    return {
        "id": str(uuid4()),
        "opened_at": utc_now_text(),
        "status": "open",
        "order_id": order["id"],
        "strategy": order["strategy"],
        "contract_symbol": candidate["contractSymbol"],
        "ticker_symbol": candidate["tickerSymbol"],
        "expiration": candidate["expiration"],
        "strike": candidate["strike"],
        "premium_received": candidate["premiumIfSoldAtBid"],
        "cash_required": candidate["cashRequired"],
        "breakeven_price": candidate["breakevenPrice"],
        "realized_pnl": 0,
    }


## Return true only when Alpaca already reports the order as filled.
def should_track_open_position(order):
    return str(order.get("status", "")).lower() in FILLED_ORDER_STATUSES


## Record a discard, failed order, or successful paper-order submission.
def record_user_decision(run_id, contract_symbol, action, note="", alpaca_order=None, order_error=None):
    run = get_recommendation_run(run_id)
    if run is None:
        raise ValueError("Recommendation run not found.")
    candidate = find_candidate(run, contract_symbol)
    if candidate is None:
        raise ValueError("Candidate not found in recommendation run.")
    decision = {
        "id": str(uuid4()),
        "created_at": utc_now_text(),
        "recommendation_run_id": run_id,
        "contract_symbol": contract_symbol,
        "ticker_symbol": candidate["tickerSymbol"],
        "action": action,
        "note": note,
        "agent_selected_contract": run["agent_review"].get("selected_contract"),
        "agent_decision": run["agent_review"].get("decision"),
        "alpaca_order_id": (alpaca_order or {}).get("id"),
        "order_error": order_error,
    }
    put_item({"pk": USER_PK, "sk": f"DECISION#{decision['created_at']}#{decision['id']}", "item_type": "user_decision", **decision})
    put_item({"pk": f"RUN#{run_id}", "sk": f"DECISION#{decision['id']}", "item_type": "user_decision", **decision})
    if action == "place_paper_order":
        order = create_paper_order(decision, candidate, alpaca_order)
        put_item({"pk": USER_PK, "sk": f"ORDER#{order['created_at']}#{order['id']}", "item_type": "paper_order", **order})
        if order.get("alpaca_order_id"):
            put_item({"pk": f"ALPACA_ORDER#{order['alpaca_order_id']}", "sk": "ORDER", "item_type": "order_lookup", "order_id": order["id"], "user_order_sk": f"ORDER#{order['created_at']}#{order['id']}"})
        if should_track_open_position(order):
            position = create_open_position(order, candidate)
            put_item({"pk": USER_PK, "sk": f"POSITION#{position['opened_at']}#{position['id']}", "item_type": "position", **position})
    return decision


## Return locally tracked positions still marked open.
def get_open_positions():
    return [
        item for item in query_items(USER_PK, "POSITION#")
        if item.get("status") == "open"
    ]


## Return saved paper orders, oldest first, for dashboard display.
def get_paper_orders(limit=20):
    orders = query_items(USER_PK, "ORDER#", limit=limit, scan_forward=False)
    return list(reversed(orders))


## Calculate local CSP collateral usage and position capacity.
def get_capital_summary(total_capital, max_csp_capital_percent, max_open_positions, open_positions=None):
    positions = get_open_positions() if open_positions is None else open_positions
    committed_capital = sum(position["cash_required"] for position in positions)
    max_csp_capital = total_capital * max_csp_capital_percent
    return {
        "total_capital": total_capital,
        "max_csp_capital": max_csp_capital,
        "committed_capital": committed_capital,
        "available_csp_capital": max(0, max_csp_capital - committed_capital),
        "open_position_count": len(positions),
        "max_open_positions": max_open_positions,
        "open_positions": positions,
    }


## Load capital calculations and recent paper order history.
def get_dashboard_data(total_capital=TOTAL_CAPITAL, max_csp_capital_percent=MAX_CSP_CAPITAL_PERCENT, max_open_positions=MAX_OPEN_POSITIONS):
    open_positions = get_open_positions()
    return {
        "capital": get_capital_summary(total_capital, max_csp_capital_percent, max_open_positions, open_positions),
        "open_positions": open_positions,
        "paper_orders": get_paper_orders(),
    }


## Synchronize saved paper orders with broker order status snapshots.
def reconcile_paper_orders(alpaca_orders):
    updated_count = 0
    for alpaca_order in alpaca_orders:
        alpaca_order_id = alpaca_order.get("id")
        status = alpaca_order.get("status")
        if not alpaca_order_id or not status:
            continue
        lookup = get_item(f"ALPACA_ORDER#{alpaca_order_id}", "ORDER")
        if not lookup:
            continue
        order_item = get_item(USER_PK, lookup["user_order_sk"])
        if not order_item:
            continue
        order_item["status"] = status
        order_item["alpaca_limit_price"] = alpaca_order.get("limit_price") or order_item.get("alpaca_limit_price")
        order_item["raw_alpaca_order"] = alpaca_order
        put_item(order_item)
        updated_count += 1
    return updated_count


## Return recent decisions and snapshots involving the requested tickers.
def get_relevant_episodes(ticker_symbols, limit=8):
    symbols = set(ticker_symbols or [])
    if not symbols:
        return []
    decisions = [
        item for item in query_items(USER_PK, "DECISION#", limit=limit * 4, scan_forward=False)
        if item.get("ticker_symbol") in symbols
    ]
    episodes = []
    for decision in decisions[:limit]:
        run = get_recommendation_run(decision["recommendation_run_id"])
        candidate = find_candidate(run, decision["contract_symbol"]) if run else None
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
            "order_status": None,
            "outcome": None,
        })
    return episodes


## Build a cautious sparse profile from available DynamoDB decision history.
def build_user_profile():
    decisions = query_items(USER_PK, "DECISION#", limit=200, scan_forward=False)
    placed = [item for item in decisions if item.get("action") == "place_paper_order"]
    discarded = [item for item in decisions if item.get("action") == "discard"]
    profile = {
        "profile_type": "observed_and_inferred",
        "evidence": {
            "total_decisions": len(decisions),
            "placed_orders": len(placed),
            "discarded_candidates": len(discarded),
            "completed_trade_outcomes": 0,
        },
        "observed_preferences": {
            "most_selected_tickers": _top_selected_tickers(placed),
            "inferred_risk_preference": {
                "label": "unknown",
                "evidence_count": len(placed),
                "confidence": "insufficient" if len(placed) < 5 else "low",
            },
        },
        "outcome_preferences": {
            "assignment_rate": None,
            "average_premium_retained_percent": None,
            "assignment_tolerance": "unknown",
        },
        "interpretation_limits": "DynamoDB memory is active, but evidence is still sparse and must not override hard rules.",
    }
    return {
        "profile": profile,
        "evidence_count": len(decisions),
        "confidence": "insufficient" if len(decisions) < 5 else "low",
    }


## Count selected tickers for a compact user preference snapshot.
def _top_selected_tickers(placed, limit=5):
    counts = {}
    for item in placed:
        ticker = item.get("ticker_symbol")
        if ticker:
            counts[ticker] = counts.get(ticker, 0) + 1
    return [
        {"value": ticker, "count": count}
        for ticker, count in sorted(counts.items(), key=lambda pair: pair[1], reverse=True)[:limit]
    ]


## Store a user profile version and return it.
def save_user_profile_version(profile_result):
    profile_id = str(uuid4())
    generated_at = utc_now_text()
    item = {
        "pk": USER_PK,
        "sk": f"PROFILE#{generated_at}#{profile_id}",
        "item_type": "user_profile_version",
        "id": profile_id,
        "generated_at": generated_at,
        "evidence_count": profile_result["evidence_count"],
        "confidence": profile_result["confidence"],
        "profile": profile_result["profile"],
    }
    put_item(item)
    return item


## Return pattern memory once enough DynamoDB outcome evidence exists.
def get_outcome_patterns(ticker_symbols=None, minimum_sample_size=5):
    return []


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
            "backend": "dynamodb",
        },
    }


## Candidate observation capture will move to EventBridge after Lambda deployment.
def capture_due_candidate_observations(limit=200):
    return {"captured": 0, "due": 0, "errors": {}, "backend": "dynamodb", "note": "Observation capture is disabled until scheduled Lambda is configured."}


## Record a realized trade result for future learning.
def record_trade_outcome(
    decision_id,
    status,
    outcome_label,
    closing_cost=None,
    realized_pnl=None,
    assigned=None,
    expired_worthless=None,
    notes="",
    raw_outcome=None,
):
    outcome_id = str(uuid4())
    updated_at = utc_now_text()
    item = {
        "pk": USER_PK,
        "sk": f"OUTCOME#{updated_at}#{outcome_id}",
        "item_type": "trade_outcome",
        "id": outcome_id,
        "decision_id": decision_id,
        "status": status,
        "outcome_label": outcome_label,
        "closing_cost": closing_cost,
        "realized_pnl": realized_pnl,
        "assigned": assigned,
        "expired_worthless": expired_worthless,
        "notes": notes,
        "raw_outcome": raw_outcome or {},
        "updated_at": updated_at,
    }
    put_item(item)
    return item
