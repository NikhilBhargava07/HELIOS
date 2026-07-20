## Record user decisions and reconcile paper orders in DynamoDB.

from uuid import uuid4

from backend.memory.dynamodb_store import (
    get_item,
    put_item,
    user_pk,
    utc_now_text,
)
from backend.memory.recommendations import (
    find_candidate,
    get_recommendation_run,
)

FILLED_ORDER_STATUSES = {"filled"}


## Convert a broker submission into the normalized HELIOS paper-order record.
## Only fields used by the dashboard and learning system are retained; the full Alpaca payload is deliberately omitted.
def _create_paper_order(decision, candidate, alpaca_order=None):
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
    }


## Build a fallback open-position record after a filled paper order.
## Live Alpaca positions remain authoritative; this record is used only when the broker position endpoint is unavailable.
def _create_open_position(order, candidate):
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


## Decide whether a broker order represents an active filled CSP position.
## Accepted but unfilled limit orders are orders rather than positions and therefore do not consume a saved position slot.
def _should_track_open_position(order):
    return str(order.get("status", "")).lower() in FILLED_ORDER_STATUSES


## Record how one authenticated user responded to a saved recommendation.
## The owner-scoped run lookup prevents users from submitting decisions against another user's candidates.
def record_user_decision(
    user_id,
    run_id,
    contract_symbol,
    action,
    note="",
    alpaca_order=None,
    order_error=None,
):
    run = get_recommendation_run(user_id, run_id)
    if run is None:
        raise ValueError("Recommendation run not found.")

    candidate = find_candidate(run, contract_symbol)
    if candidate is None:
        raise ValueError("Candidate not found in recommendation run.")

    owner_partition = user_pk(user_id)
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
    put_item({
        "pk": owner_partition,
        "sk": f"DECISION#{decision['created_at']}#{decision['id']}",
        "item_type": "user_decision",
        **decision,
    })

    if action != "place_paper_order":
        return decision

    order = _create_paper_order(decision, candidate, alpaca_order)
    order_sort_key = f"ORDER#{order['created_at']}#{order['id']}"
    put_item({
        "pk": owner_partition,
        "sk": order_sort_key,
        "item_type": "paper_order",
        **order,
    })
    if order.get("alpaca_order_id"):
        put_item({
            "pk": f"{owner_partition}#ALPACA_ORDER#{order['alpaca_order_id']}",
            "sk": "ORDER",
            "item_type": "order_lookup",
            "order_id": order["id"],
            "user_order_sk": order_sort_key,
        })
    if _should_track_open_position(order):
        position = _create_open_position(order, candidate)
        put_item({
            "pk": owner_partition,
            "sk": f"POSITION#{position['opened_at']}#{position['id']}",
            "item_type": "position",
            **position,
        })
    return decision


## Update saved order records from the latest Alpaca statuses for one user.
## User-scoped lookup keys prevent identical broker order ids from crossing HELIOS account boundaries.
def reconcile_paper_orders(user_id, alpaca_orders):
    owner_partition = user_pk(user_id)
    updated_count = 0
    for alpaca_order in alpaca_orders:
        alpaca_order_id = alpaca_order.get("id")
        status = alpaca_order.get("status")
        if not alpaca_order_id or not status:
            continue

        lookup = get_item(
            f"{owner_partition}#ALPACA_ORDER#{alpaca_order_id}",
            "ORDER",
        )
        if not lookup:
            continue

        order_item = get_item(owner_partition, lookup["user_order_sk"])
        if not order_item:
            continue

        order_item["status"] = status
        order_item["alpaca_limit_price"] = (
            alpaca_order.get("limit_price")
            or order_item.get("alpaca_limit_price")
        )
        put_item(order_item)
        updated_count += 1
    return updated_count
