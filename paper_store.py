from uuid import uuid4

from psycopg.types.json import Jsonb

from database import ensure_schema, get_connection, json_safe, utc_now


EMPTY_STORE = {
    "recommendation_runs": [],
    "user_decisions": [],
    "paper_orders": [],
    "positions": [],
}

FILLED_ORDER_STATUSES = {"filled"}


def normalize_candidate(candidate):
    return {
        "tickerSymbol": candidate["tickerSymbol"],
        "contractSymbol": candidate["contractSymbol"],
        "expiration": candidate["expiration"],
        "DTE": candidate["DTE"],
        "strike": candidate["strike"],
        "currentStockPrice": candidate.get("currentStockPrice"),
        "delta": candidate.get("delta"),
        "ivPercent": candidate.get("ivPercent"),
        "spread": candidate.get("spread"),
        "premiumIfSoldAtBid": candidate.get("premiumIfSoldAtBid"),
        "cashRequired": candidate.get("cashRequired"),
        "breakevenPrice": candidate.get("breakevenPrice"),
        "returnOnCashPercent": candidate.get("returnOnCashPercent"),
        "companyName": candidate.get("companyName"),
    }


def candidate_from_row(row):
    raw_candidate = row.get("raw_candidate") or {}
    candidate = normalize_candidate(
        {
            "tickerSymbol": row["ticker_symbol"],
            "contractSymbol": row["contract_symbol"],
            "expiration": row["expiration"],
            "DTE": row["dte"],
            "strike": row["strike"],
            "currentStockPrice": row["current_stock_price"],
            "delta": row["delta"],
            "ivPercent": row["iv_percent"],
            "spread": row["spread"],
            "premiumIfSoldAtBid": row["premium_if_sold_at_bid"],
            "cashRequired": row["cash_required"],
            "breakevenPrice": row["breakeven_price"],
            "returnOnCashPercent": row["return_on_cash_percent"],
            "companyName": row["company_name"],
        }
    )
    candidate.update(raw_candidate)

    return json_safe(candidate)


def run_from_row(row, candidates):
    return json_safe(
        {
            "id": row["id"],
            "created_at": row["created_at"],
            "candidates": candidates,
            "agent_review": row["agent_review"],
        }
    )


def decision_from_row(row):
    return json_safe(
        {
            "id": row["id"],
            "created_at": row["created_at"],
            "recommendation_run_id": row["recommendation_run_id"],
            "contract_symbol": row["contract_symbol"],
            "ticker_symbol": row["ticker_symbol"],
            "action": row["action"],
            "note": row["note"] or "",
            "agent_selected_contract": row["agent_selected_contract"],
            "agent_decision": row["agent_decision"],
            "alpaca_order_id": row.get("alpaca_order_id"),
            "order_error": row.get("order_error"),
        }
    )


def order_from_row(row):
    return json_safe(
        {
            "id": row["id"],
            "created_at": row["created_at"],
            "decision_id": row["decision_id"],
            "status": row["status"],
            "side": row["side"],
            "strategy": row["strategy"],
            "contract_symbol": row["contract_symbol"],
            "ticker_symbol": row["ticker_symbol"],
            "expiration": row["expiration"],
            "strike": row["strike"],
            "premium_received": row["premium_received"],
            "cash_required": row["cash_required"],
            "breakeven_price": row["breakeven_price"],
            "alpaca_order_id": row.get("alpaca_order_id"),
            "alpaca_client_order_id": row.get("alpaca_client_order_id"),
            "alpaca_limit_price": row.get("alpaca_limit_price"),
            "alpaca_submitted_at": row.get("alpaca_submitted_at"),
            "raw_alpaca_order": row.get("raw_alpaca_order"),
        }
    )


def position_from_row(row):
    return json_safe(
        {
            "id": row["id"],
            "opened_at": row["opened_at"],
            "closed_at": row.get("closed_at"),
            "status": row["status"],
            "order_id": row["order_id"],
            "strategy": row["strategy"],
            "contract_symbol": row["contract_symbol"],
            "ticker_symbol": row["ticker_symbol"],
            "expiration": row["expiration"],
            "strike": row["strike"],
            "premium_received": row["premium_received"],
            "cash_required": row["cash_required"],
            "breakeven_price": row["breakeven_price"],
            "realized_pnl": row["realized_pnl"],
        }
    )


def load_store():
    ensure_schema()

    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT *
                FROM recommendation_runs
                ORDER BY created_at ASC
                """
            )
            run_rows = cursor.fetchall()

            cursor.execute(
                """
                SELECT *
                FROM csp_candidates
                ORDER BY created_at ASC
                """
            )
            candidate_rows = cursor.fetchall()

            cursor.execute("SELECT * FROM user_decisions ORDER BY created_at ASC")
            decision_rows = cursor.fetchall()

            cursor.execute("SELECT * FROM paper_orders ORDER BY created_at ASC")
            order_rows = cursor.fetchall()

            cursor.execute("SELECT * FROM positions ORDER BY opened_at ASC")
            position_rows = cursor.fetchall()

    candidates_by_run = {}

    for candidate_row in candidate_rows:
        run_id = str(candidate_row["recommendation_run_id"])
        candidates_by_run.setdefault(run_id, []).append(candidate_from_row(candidate_row))

    return {
        "recommendation_runs": [
            run_from_row(row, candidates_by_run.get(str(row["id"]), []))
            for row in run_rows
        ],
        "user_decisions": [decision_from_row(row) for row in decision_rows],
        "paper_orders": [order_from_row(row) for row in order_rows],
        "positions": [position_from_row(row) for row in position_rows],
    }


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


def get_recommendation_run(run_id):
    ensure_schema()

    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT * FROM recommendation_runs WHERE id = %s",
                (run_id,),
            )
            run_row = cursor.fetchone()

            if run_row is None:
                return None

            cursor.execute(
                """
                SELECT *
                FROM csp_candidates
                WHERE recommendation_run_id = %s
                ORDER BY created_at ASC
                """,
                (run_id,),
            )
            candidates = [candidate_from_row(row) for row in cursor.fetchall()]

    return run_from_row(run_row, candidates)


def get_latest_recommendation_run():
    ensure_schema()

    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT id FROM recommendation_runs ORDER BY created_at DESC LIMIT 1"
            )
            row = cursor.fetchone()

    if row is None:
        return None

    return get_recommendation_run(str(row["id"]))


def save_recommendation_run(candidates, review):
    ensure_schema()
    run_id = str(uuid4())
    created_at = utc_now()

    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO recommendation_runs (id, created_at, agent_review)
                VALUES (%s, %s, %s)
                """,
                (run_id, created_at, Jsonb(review)),
            )

            for candidate in candidates:
                cursor.execute(
                    """
                    INSERT INTO csp_candidates (
                        id,
                        recommendation_run_id,
                        contract_symbol,
                        ticker_symbol,
                        company_name,
                        expiration,
                        dte,
                        strike,
                        current_stock_price,
                        delta,
                        iv_percent,
                        spread,
                        premium_if_sold_at_bid,
                        cash_required,
                        breakeven_price,
                        return_on_cash_percent,
                        raw_candidate,
                        created_at
                    )
                    VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    """,
                    (
                        str(uuid4()),
                        run_id,
                        candidate["contractSymbol"],
                        candidate["tickerSymbol"],
                        candidate.get("companyName"),
                        candidate["expiration"],
                        candidate["DTE"],
                        candidate["strike"],
                        candidate.get("currentStockPrice"),
                        candidate.get("delta"),
                        candidate.get("ivPercent"),
                        candidate.get("spread"),
                        candidate.get("premiumIfSoldAtBid"),
                        candidate.get("cashRequired"),
                        candidate.get("breakevenPrice"),
                        candidate.get("returnOnCashPercent"),
                        Jsonb(candidate),
                        created_at,
                    ),
                )

    return {
        "id": run_id,
        "created_at": created_at.isoformat(),
        "candidates": candidates,
        "agent_review": review,
    }


def record_user_decision(run_id, contract_symbol, action, note="", alpaca_order=None, order_error=None):
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
            cursor.execute(
                """
                INSERT INTO user_decisions (
                    id,
                    created_at,
                    recommendation_run_id,
                    contract_symbol,
                    ticker_symbol,
                    action,
                    note,
                    agent_selected_contract,
                    agent_decision,
                    alpaca_order_id,
                    order_error
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    decision["id"],
                    decision["created_at"],
                    decision["recommendation_run_id"],
                    decision["contract_symbol"],
                    decision["ticker_symbol"],
                    decision["action"],
                    decision["note"],
                    decision["agent_selected_contract"],
                    decision["agent_decision"],
                    decision["alpaca_order_id"],
                    decision["order_error"],
                ),
            )

            if action == "place_paper_order":
                order = create_paper_order(decision, candidate, alpaca_order)
                insert_paper_order(cursor, order)

                if should_track_open_position(order):
                    position = create_open_position(order, candidate)
                    insert_position(cursor, position)

    return decision


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


def insert_paper_order(cursor, order):
    cursor.execute(
        """
        INSERT INTO paper_orders (
            id,
            created_at,
            decision_id,
            status,
            side,
            strategy,
            contract_symbol,
            ticker_symbol,
            expiration,
            strike,
            premium_received,
            cash_required,
            breakeven_price,
            alpaca_order_id,
            alpaca_client_order_id,
            alpaca_limit_price,
            alpaca_submitted_at,
            raw_alpaca_order
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            order["id"],
            order["created_at"],
            order["decision_id"],
            order["status"],
            order["side"],
            order["strategy"],
            order["contract_symbol"],
            order["ticker_symbol"],
            order["expiration"],
            order["strike"],
            order["premium_received"],
            order["cash_required"],
            order["breakeven_price"],
            order["alpaca_order_id"],
            order["alpaca_client_order_id"],
            order["alpaca_limit_price"],
            order["alpaca_submitted_at"],
            Jsonb(order["raw_alpaca_order"]),
        ),
    )


def should_track_open_position(order):
    return str(order.get("status", "")).lower() in FILLED_ORDER_STATUSES


def create_open_position(order, candidate):
    return {
        "id": str(uuid4()),
        "opened_at": utc_now().isoformat(),
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


def insert_position(cursor, position):
    cursor.execute(
        """
        INSERT INTO positions (
            id,
            opened_at,
            status,
            order_id,
            strategy,
            contract_symbol,
            ticker_symbol,
            expiration,
            strike,
            premium_received,
            cash_required,
            breakeven_price,
            realized_pnl
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            position["id"],
            position["opened_at"],
            position["status"],
            position["order_id"],
            position["strategy"],
            position["contract_symbol"],
            position["ticker_symbol"],
            position["expiration"],
            position["strike"],
            position["premium_received"],
            position["cash_required"],
            position["breakeven_price"],
            position["realized_pnl"],
        ),
    )


def get_open_positions():
    ensure_schema()

    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT *
                FROM positions
                WHERE status = 'open'
                ORDER BY opened_at ASC
                """
            )
            return [position_from_row(row) for row in cursor.fetchall()]


def get_capital_summary(total_capital, max_csp_capital_percent, max_open_positions, open_positions=None):
    if open_positions is None:
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
    ensure_schema()
    open_positions = get_open_positions()

    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT * FROM paper_orders ORDER BY created_at DESC LIMIT 20")
            paper_orders = [order_from_row(row) for row in cursor.fetchall()]

            cursor.execute("SELECT * FROM user_decisions ORDER BY created_at DESC LIMIT 20")
            user_decisions = [decision_from_row(row) for row in cursor.fetchall()]

            cursor.execute("SELECT * FROM recommendation_runs ORDER BY created_at DESC LIMIT 10")
            recommendation_rows = cursor.fetchall()

    return {
        "capital": get_capital_summary(
            total_capital,
            max_csp_capital_percent,
            max_open_positions,
            open_positions=open_positions,
        ),
        "open_positions": open_positions,
        "paper_orders": list(reversed(paper_orders)),
        "user_decisions": list(reversed(user_decisions)),
        "recommendation_runs": [run_from_row(row, []) for row in reversed(recommendation_rows)],
    }
