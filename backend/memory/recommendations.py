## Persist and retrieve recommendation runs and their candidate snapshots.

from uuid import uuid4

from backend.config import MEMORY_BACKEND
from backend.memory.database import ensure_schema, get_connection, jsonb, utc_now
from backend.memory.serializers import candidate_from_row, recommendation_from_row


def using_dynamodb():
    return MEMORY_BACKEND == "dynamodb"


## Find a contract inside a previously saved recommendation run.
def find_candidate(run, contract_symbol):
    if using_dynamodb():
        from backend.memory import dynamodb_store
        return dynamodb_store.find_candidate(run, contract_symbol)
    return next(
        (candidate for candidate in run["candidates"] if candidate["contractSymbol"] == contract_symbol),
        None,
    )


## Load one recommendation run and all candidates using targeted SQL.
def get_recommendation_run(run_id):
    if using_dynamodb():
        from backend.memory import dynamodb_store
        return dynamodb_store.get_recommendation_run(run_id)
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


## Load the most recently generated recommendation run.
def get_latest_recommendation_run():
    if using_dynamodb():
        from backend.memory import dynamodb_store
        return dynamodb_store.get_latest_recommendation_run()
    ensure_schema()
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT id FROM recommendation_runs ORDER BY created_at DESC LIMIT 1")
            row = cursor.fetchone()
    return get_recommendation_run(str(row["id"])) if row else None


## Save an AI review and the complete evidence snapshot it received.
def save_recommendation_run(
    candidates,
    review,
    market_context=None,
    strategy_rules=None,
    portfolio_context=None,
    memory_context=None,
):
    if using_dynamodb():
        from backend.memory import dynamodb_store
        return dynamodb_store.save_recommendation_run(
            candidates,
            review,
            market_context=market_context,
            strategy_rules=strategy_rules,
            portfolio_context=portfolio_context,
            memory_context=memory_context,
        )
    ensure_schema()
    run_id = str(uuid4())
    created_at = utc_now()
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO recommendation_runs (
                    id, created_at, agent_review, market_context, strategy_rules,
                    portfolio_context, memory_context
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    run_id, created_at, jsonb(review), jsonb(market_context or {}),
                    jsonb(strategy_rules or {}), jsonb(portfolio_context or {}),
                    jsonb(memory_context or {}),
                ),
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
                        jsonb(candidate), created_at,
                    ),
                )
    return {
        "id": run_id,
        "created_at": created_at.isoformat(),
        "candidates": candidates,
        "agent_review": review,
        "market_context": market_context or {},
        "strategy_rules": strategy_rules or {},
        "portfolio_context": portfolio_context or {},
        "memory_context": memory_context or {},
    }
