"""Persist user decisions, paper orders, and locally observed filled positions."""

from uuid import uuid4

from psycopg.types.json import Jsonb

from backend.memory.database import ensure_schema, get_connection, utc_now
from backend.memory.recommendations import find_candidate, get_recommendation_run

FILLED_ORDER_STATUSES = {"filled"}


def record_user_decision(
    run_id,
    contract_symbol,
    action,
    note="",
    alpaca_order=None,
    order_error=None,
):
    """Record a discard, failed order, or successful order submission."""
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


def _insert_decision(cursor, decision):
    """Insert one normalized user decision using the active transaction."""
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


def create_paper_order(decision, candidate, alpaca_order=None):
    """Build the database representation of a submitted Alpaca paper order."""
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


def insert_paper_order(cursor, order):
    """Insert one paper order using the active decision transaction."""
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
            Jsonb(order["raw_alpaca_order"]),
        ),
    )


def should_track_open_position(order):
    """Return true only when Alpaca already reports the order as filled."""
    return str(order.get("status", "")).lower() in FILLED_ORDER_STATUSES


def create_open_position(order, candidate):
    """Build a local position record from a filled paper order."""
    return {
        "id": str(uuid4()), "opened_at": utc_now().isoformat(), "status": "open",
        "order_id": order["id"], "strategy": order["strategy"],
        "contract_symbol": candidate["contractSymbol"],
        "ticker_symbol": candidate["tickerSymbol"], "expiration": candidate["expiration"],
        "strike": candidate["strike"], "premium_received": candidate["premiumIfSoldAtBid"],
        "cash_required": candidate["cashRequired"], "breakeven_price": candidate["breakevenPrice"],
        "realized_pnl": 0,
    }


def insert_position(cursor, position):
    """Insert one locally tracked filled position."""
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


def reconcile_paper_orders(alpaca_orders):
    """Update saved order statuses and broker details from Alpaca snapshots."""
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
                        Jsonb(order),
                        order_id,
                    ),
                )
                updated_count += cursor.rowcount
    return updated_count
