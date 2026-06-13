import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


DATA_DIR = Path(__file__).with_name("data")
STORE_PATH = DATA_DIR / "paper_store.json"


EMPTY_STORE = {
    "recommendation_runs": [],
    "user_decisions": [],
    "paper_orders": [],
    "positions": [],
}


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def load_store():
    if not STORE_PATH.exists():
        return EMPTY_STORE.copy()

    with STORE_PATH.open("r", encoding="utf-8") as store_file:
        loaded_store = json.load(store_file)

    store = EMPTY_STORE.copy()
    store.update(loaded_store)

    return store


def save_store(store):
    DATA_DIR.mkdir(exist_ok=True)

    with STORE_PATH.open("w", encoding="utf-8") as store_file:
        json.dump(store, store_file, indent=2)


def save_recommendation_run(candidates, review):
    store = load_store()
    run_id = str(uuid4())

    run = {
        "id": run_id,
        "created_at": utc_now(),
        "candidates": candidates,
        "agent_review": review,
    }

    store["recommendation_runs"].append(run)
    save_store(store)

    return run


def find_recommendation_run(store, run_id):
    for run in store["recommendation_runs"]:
        if run["id"] == run_id:
            return run

    return None


def find_candidate(run, contract_symbol):
    for candidate in run["candidates"]:
        if candidate["contractSymbol"] == contract_symbol:
            return candidate

    return None


NON_OPEN_ORDER_STATUSES = {
    "canceled",
    "expired",
    "rejected",
}


def record_user_decision(run_id, contract_symbol, action, note="", alpaca_order=None, order_error=None):
    store = load_store()
    run = find_recommendation_run(store, run_id)

    if run is None:
        raise ValueError("Recommendation run not found.")

    candidate = find_candidate(run, contract_symbol)

    if candidate is None:
        raise ValueError("Candidate not found in recommendation run.")

    decision = {
        "id": str(uuid4()),
        "created_at": utc_now(),
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

    store["user_decisions"].append(decision)

    if action == "place_paper_order":
        order = create_paper_order(decision, candidate, alpaca_order)
        store["paper_orders"].append(order)

        if should_track_open_position(order):
            position = create_open_position(order, candidate)
            store["positions"].append(position)

    save_store(store)

    return decision


def create_paper_order(decision, candidate, alpaca_order=None):
    alpaca_order = alpaca_order or {}

    return {
        "id": str(uuid4()),
        "created_at": utc_now(),
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
        "raw_alpaca_order": alpaca_order.get("raw_order"),
    }


def should_track_open_position(order):
    return str(order.get("status", "")).lower() not in NON_OPEN_ORDER_STATUSES


def create_open_position(order, candidate):
    return {
        "id": str(uuid4()),
        "opened_at": utc_now(),
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


def get_open_positions():
    store = load_store()

    return [
        position
        for position in store["positions"]
        if position["status"] == "open"
    ]


def get_capital_summary(total_capital, max_csp_capital_percent, max_open_positions):
    open_positions = get_open_positions()
    committed_capital = sum(position["cash_required"] for position in open_positions)
    max_csp_capital = total_capital * max_csp_capital_percent

    return {
        "total_capital": total_capital,
        "max_csp_capital": max_csp_capital,
        "committed_capital": committed_capital,
        "available_csp_capital": max(0, max_csp_capital - committed_capital),
        "open_position_count": len(open_positions),
        "max_open_positions": max_open_positions,
        "open_positions": open_positions,
    }


def get_dashboard_data(total_capital, max_csp_capital_percent, max_open_positions):
    store = load_store()

    return {
        "capital": get_capital_summary(
            total_capital,
            max_csp_capital_percent,
            max_open_positions,
        ),
        "open_positions": get_open_positions(),
        "paper_orders": store["paper_orders"][-20:],
        "user_decisions": store["user_decisions"][-20:],
        "recommendation_runs": store["recommendation_runs"][-10:],
    }
