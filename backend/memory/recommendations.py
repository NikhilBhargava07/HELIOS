"""Persist and retrieve recommendation runs and their candidate snapshots."""

from uuid import uuid4

from psycopg.types.json import Jsonb

from backend.memory.database import ensure_schema, get_connection, utc_now
from backend.memory.serializers import candidate_from_row, recommendation_from_row


def find_candidate(run, contract_symbol):
    """Find a contract inside a previously saved recommendation run."""
    return next(
        (candidate for candidate in run["candidates"] if candidate["contractSymbol"] == contract_symbol),
        None,
    )


def get_recommendation_run(run_id):
    """Load one recommendation run and all candidates using targeted SQL."""
    ensure_schema()
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT * FROM recommendation_runs WHERE id = %s", (run_id,))
            run_row = cursor.fetchone()
            if run_row is None:
                return None
            cursor.execute(
                "SELECT * FROM csp_candidates WHERE recommendation_run_id = %s ORDER BY created_at ASC",
                (run_id,),
            )
            candidates = [candidate_from_row(row) for row in cursor.fetchall()]
    return recommendation_from_row(run_row, candidates)


def get_latest_recommendation_run():
    """Load the most recently generated recommendation run."""
    ensure_schema()
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT id FROM recommendation_runs ORDER BY created_at DESC LIMIT 1")
            row = cursor.fetchone()
    return get_recommendation_run(str(row["id"])) if row else None


def save_recommendation_run(candidates, review):
    """Save an AI review and immutable snapshot of its candidate list."""
    ensure_schema()
    run_id = str(uuid4())
    created_at = utc_now()
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO recommendation_runs (id, created_at, agent_review) VALUES (%s, %s, %s)",
                (run_id, created_at, Jsonb(review)),
            )
            for candidate in candidates:
                cursor.execute(
                    """
                    INSERT INTO csp_candidates (
                        id, recommendation_run_id, contract_symbol, ticker_symbol,
                        company_name, expiration, dte, strike, current_stock_price,
                        delta, iv_percent, spread, premium_if_sold_at_bid,
                        cash_required, breakeven_price, return_on_cash_percent,
                        raw_candidate, created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        str(uuid4()), run_id, candidate["contractSymbol"],
                        candidate["tickerSymbol"], candidate.get("companyName"),
                        candidate["expiration"], candidate["DTE"], candidate["strike"],
                        candidate.get("currentStockPrice"), candidate.get("delta"),
                        candidate.get("ivPercent"), candidate.get("spread"),
                        candidate.get("premiumIfSoldAtBid"), candidate.get("cashRequired"),
                        candidate.get("breakevenPrice"), candidate.get("returnOnCashPercent"),
                        Jsonb(candidate), created_at,
                    ),
                )
    return {
        "id": run_id,
        "created_at": created_at.isoformat(),
        "candidates": candidates,
        "agent_review": review,
    }
