## Persist user decisions, paper orders, and locally observed filled positions.

from uuid import uuid4

from backend.config import MEMORY_BACKEND
from backend.memory.database import ensure_schema, get_connection, jsonb, utc_now
from backend.memory.recommendations import find_candidate, get_recommendation_run

FILLED_ORDER_STATUSES = {"filled"}


def using_dynamodb():
    return MEMORY_BACKEND == "dynamodb"


## Record a discard, failed order, or successful order submission.
def record_user_decision(
    run_id,
    contract_symbol,
    action,
    note="",
    alpaca_order=None,
    order_error=None,
):
    if using_dynamodb():
        from backend.memory import dynamodb_store
        return dynamodb_store.record_user_decision(
            run_id,
            contract_symbol,
            action,
            note=note,
            alpaca_order=alpaca_order,
            order_error=order_error,
        )
    ensure_schema()
    run = get_recommendation_run(run_id)
    if run is None:
        raise ValueError("Recommendation run not found.")

    candidate = find_candidate(run, contract_symbol)
    if candidate is None:
        raise ValueError("Candidate not found in recommendation run.")

    decision = {
        "id": str(uuid4()),
        "created_at": utc_now().isoformat(),
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

    with get_connection() as connection:
        with connection.cursor() as cursor:
            _insert_decision(cursor, decision)
            if action == "place_paper_order":
                order = create_paper_order(decision, candidate, alpaca_order)
                insert_paper_order(cursor, order)
                if should_track_open_position(order):
                    insert_position(cursor, create_open_position(order, candidate))
    return decision


## Insert one normalized user decision using the active transaction.
def _insert_decision(cursor, decision):
    cursor.execute(
        """
        INSERT INTO user_decisions (
            id, created_at, recommendation_run_id, contract_symbol,
            ticker_symbol, action, note, agent_selected_contract,
            agent_decision, alpaca_order_id, order_error
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            decision["id"], decision["created_at"], decision["recommendation_run_id"],
            decision["contract_symbol"], decision["ticker_symbol"], decision["action"],
            decision["note"], decision["agent_selected_contract"],
            decision["agent_decision"], decision["alpaca_order_id"], decision["order_error"],
        ),
    )


## Build the database representation of a submitted Alpaca paper order.
def create_paper_order(decision, candidate, alpaca_order=None):
    alpaca_order = alpaca_order or {}
    return {
        "id": str(uuid4()),
        "created_at": utc_now().isoformat(),
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


## Insert one paper order using the active decision transaction.
def insert_paper_order(cursor, order):
    cursor.execute(
        """
        INSERT INTO paper_orders (
            id, created_at, decision_id, status, side, strategy,
            contract_symbol, ticker_symbol, expiration, strike,
            premium_received, cash_required, breakeven_price,
            alpaca_order_id, alpaca_client_order_id, alpaca_limit_price,
            alpaca_submitted_at, raw_alpaca_order
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            order["id"], order["created_at"], order["decision_id"], order["status"],
            order["side"], order["strategy"], order["contract_symbol"],
            order["ticker_symbol"], order["expiration"], order["strike"],
            order["premium_received"], order["cash_required"], order["breakeven_price"],
            order["alpaca_order_id"], order["alpaca_client_order_id"],
            order["alpaca_limit_price"], order["alpaca_submitted_at"],
            jsonb(order["raw_alpaca_order"]),
        ),
    )


## Return true only when Alpaca already reports the order as filled.
def should_track_open_position(order):
    return str(order.get("status", "")).lower() in FILLED_ORDER_STATUSES


## Build a local position record from a filled paper order.
def create_open_position(order, candidate):
    return {
        "id": str(uuid4()), "opened_at": utc_now().isoformat(), "status": "open",
        "order_id": order["id"], "strategy": order["strategy"],
        "contract_symbol": candidate["contractSymbol"],
        "ticker_symbol": candidate["tickerSymbol"], "expiration": candidate["expiration"],
        "strike": candidate["strike"], "premium_received": candidate["premiumIfSoldAtBid"],
        "cash_required": candidate["cashRequired"], "breakeven_price": candidate["breakevenPrice"],
        "realized_pnl": 0,
    }


## Insert one locally tracked filled position.
def insert_position(cursor, position):
    cursor.execute(
        """
        INSERT INTO positions (
            id, opened_at, status, order_id, strategy, contract_symbol,
            ticker_symbol, expiration, strike, premium_received,
            cash_required, breakeven_price, realized_pnl
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            position["id"], position["opened_at"], position["status"], position["order_id"],
            position["strategy"], position["contract_symbol"], position["ticker_symbol"],
            position["expiration"], position["strike"], position["premium_received"],
            position["cash_required"], position["breakeven_price"], position["realized_pnl"],
        ),
    )


## Update saved order statuses and broker details from Alpaca snapshots.
def reconcile_paper_orders(alpaca_orders):
    if using_dynamodb():
        from backend.memory import dynamodb_store
        return dynamodb_store.reconcile_paper_orders(alpaca_orders)
    ensure_schema()
    updated_count = 0
    with get_connection() as connection:
        with connection.cursor() as cursor:
            for order in alpaca_orders:
                order_id = order.get("id")
                status = order.get("status")
                if not order_id or not status:
                    continue
                cursor.execute(
                    """
                    UPDATE paper_orders
                    SET status = %s,
                        alpaca_limit_price = COALESCE(%s, alpaca_limit_price),
                        raw_alpaca_order = %s
                    WHERE alpaca_order_id = %s
                    """,
                    (
                        status,
                        order.get("limit_price"),
                        jsonb(order),
                        order_id,
                    ),
                )
                updated_count += cursor.rowcount
    return updated_count
