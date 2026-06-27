## Capture candidate checkpoints and persist finalized trade outcomes.

from collections import defaultdict
from datetime import date
from uuid import uuid4

from alpaca.data.enums import OptionsFeed
from alpaca.data.requests import OptionChainRequest
from alpaca.trading.enums import ContractType
from backend.broker.clients import get_option_data_client
from backend.market.trends import get_latest_stock_prices
from backend.config import MEMORY_BACKEND
from backend.memory.database import ensure_schema, get_connection, json_safe, jsonb, utc_now


def using_dynamodb():
    return MEMORY_BACKEND == "dynamodb"


OBSERVATION_HORIZONS = (1, 5, 10, 30)


## Return candidate/horizon pairs whose calendar-day checkpoint is due.
def _due_candidates(limit):
    ensure_schema()
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT c.*, r.created_at AS recommended_at, h.horizon_days
                FROM csp_candidates c
                JOIN recommendation_runs r ON r.id = c.recommendation_run_id
                CROSS JOIN (VALUES (1), (5), (10), (30)) AS h(horizon_days)
                LEFT JOIN candidate_observations o
                  ON o.candidate_id = c.id AND o.horizon_days = h.horizon_days
                WHERE o.id IS NULL
                  AND r.created_at <= NOW() - (h.horizon_days * INTERVAL '1 day')
                ORDER BY r.created_at ASC, h.horizon_days ASC
                LIMIT %s
                """,
                (limit,),
            )
            return cursor.fetchall()


## Fetch current option quotes in one chain request per underlying ticker.
def _option_quotes(candidates):
    option_data_client = get_option_data_client()
    grouped = defaultdict(list)
    for candidate in candidates:
        grouped[candidate["ticker_symbol"]].append(candidate)

    quotes = {}
    errors = {}
    for ticker_symbol, rows in grouped.items():
        expirations = [row["expiration"] for row in rows]
        request = OptionChainRequest(
            underlying_symbol=ticker_symbol,
            type=ContractType.PUT,
            feed=OptionsFeed.INDICATIVE,
            expiration_date_gte=min(expirations).isoformat(),
            expiration_date_lte=max(expirations).isoformat(),
        )
        try:
            snapshots = option_data_client.get_option_chain(request)
        except Exception as error:
            errors[ticker_symbol] = str(error)
            continue
        for row in rows:
            snapshot = snapshots.get(row["contract_symbol"])
            quote = snapshot.latest_quote if snapshot else None
            if quote is None:
                continue
            bid = float(quote.bid_price or 0)
            ask = float(quote.ask_price or 0)
            quotes[row["contract_symbol"]] = {
                "bid": bid or None,
                "ask": ask or None,
                "mark": ((bid + ask) / 2) if bid > 0 and ask > 0 else None,
                "iv_percent": (
                    float(snapshot.implied_volatility) * 100
                    if snapshot.implied_volatility is not None else None
                ),
                "delta": float(snapshot.greeks.delta) if snapshot.greeks else None,
            }
    return quotes, errors


## Describe where the underlying sits relative to CSP expiration levels.
def _price_zone(stock_price, strike, breakeven):
    if stock_price is None:
        return "unknown"
    if stock_price >= strike:
        return "above_strike"
    if breakeven is not None and stock_price >= breakeven:
        return "below_strike_above_breakeven"
    return "below_breakeven"


## Calculate hypothetical CSP performance from current market evidence.
def _observation_values(candidate, stock_price, quote):
    strike = float(candidate["strike"])
    breakeven = (
        float(candidate["breakeven_price"])
        if candidate.get("breakeven_price") is not None else None
    )
    initial_stock = (
        float(candidate["current_stock_price"])
        if candidate.get("current_stock_price") is not None else None
    )
    premium = (
        float(candidate["premium_if_sold_at_bid"])
        if candidate.get("premium_if_sold_at_bid") is not None else None
    )
    close_cost = quote.get("ask") * 100 if quote and quote.get("ask") else None

    if close_cost is None and candidate["expiration"] <= date.today() and stock_price is not None:
        close_cost = max(strike - stock_price, 0) * 100

    estimated_pnl = premium - close_cost if premium is not None and close_cost is not None else None
    retained = (
        estimated_pnl / premium * 100
        if estimated_pnl is not None and premium and premium > 0 else None
    )
    stock_return = (
        (stock_price - initial_stock) / initial_stock * 100
        if stock_price is not None and initial_stock else None
    )
    return {
        "stock_return_percent": stock_return,
        "estimated_close_cost": close_cost,
        "estimated_pnl": estimated_pnl,
        "premium_retained_percent": retained,
        "price_zone": _price_zone(stock_price, strike, breakeven),
    }


## Capture due 1/5/10/30-day hypothetical candidate checkpoints.
def capture_due_candidate_observations(limit=200):
    if using_dynamodb():
        from backend.memory import dynamodb_store
        return dynamodb_store.capture_due_candidate_observations(limit=limit)
    candidates = _due_candidates(limit)
    if not candidates:
        return {"captured": 0, "due": 0, "errors": {}}

    ticker_symbols = list(dict.fromkeys(row["ticker_symbol"] for row in candidates))
    try:
        latest_prices = get_latest_stock_prices(ticker_symbols)
        price_error = None
    except Exception as error:
        latest_prices = {}
        price_error = str(error)
    quotes, quote_errors = _option_quotes(candidates)
    observed_at = utc_now()
    captured = 0

    with get_connection() as connection:
        with connection.cursor() as cursor:
            for candidate in candidates:
                price_record = latest_prices.get(candidate["ticker_symbol"], {})
                stock_price = price_record.get("price")
                quote = quotes.get(candidate["contract_symbol"], {})
                if stock_price is None and not quote:
                    continue
                values = _observation_values(candidate, stock_price, quote)
                raw_snapshot = {
                    "price_timestamp": price_record.get("timestamp"),
                    "option_quote": quote,
                    "price_error": price_error,
                    "quote_error": quote_errors.get(candidate["ticker_symbol"]),
                    "observation_kind": "counterfactual_candidate_checkpoint",
                }
                cursor.execute(
                    """
                    INSERT INTO candidate_observations (
                        id, candidate_id, recommendation_run_id, contract_symbol,
                        ticker_symbol, horizon_days, observed_at, stock_price,
                        stock_return_percent, option_bid, option_ask, option_mark,
                        estimated_close_cost, estimated_pnl, premium_retained_percent,
                        price_zone, raw_snapshot
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                              %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (candidate_id, horizon_days) DO NOTHING
                    """,
                    (
                        str(uuid4()), candidate["id"], candidate["recommendation_run_id"],
                        candidate["contract_symbol"], candidate["ticker_symbol"],
                        candidate["horizon_days"], observed_at, stock_price,
                        values["stock_return_percent"], quote.get("bid"), quote.get("ask"),
                        quote.get("mark"), values["estimated_close_cost"],
                        values["estimated_pnl"], values["premium_retained_percent"],
                        values["price_zone"], jsonb(raw_snapshot),
                    ),
                )
                captured += cursor.rowcount
    return {
        "captured": captured,
        "due": len(candidates),
        "horizons_are_calendar_days": True,
        "errors": {"prices": price_error, "option_quotes": quote_errors},
    }


## Create or update a realized outcome without confusing it with a forecast.
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
    if using_dynamodb():
        from backend.memory import dynamodb_store
        return dynamodb_store.record_trade_outcome(
            decision_id,
            status,
            outcome_label,
            closing_cost=closing_cost,
            realized_pnl=realized_pnl,
            assigned=assigned,
            expired_worthless=expired_worthless,
            notes=notes,
            raw_outcome=raw_outcome,
        )
    ensure_schema()
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT d.*, p.id AS paper_order_id,
                       COALESCE(
                           NULLIF(p.raw_alpaca_order->>'filled_avg_price', '')::NUMERIC * 100,
                           p.premium_received
                       ) AS premium_received,
                       p.contract_symbol, p.ticker_symbol, p.alpaca_submitted_at
                FROM user_decisions d
                LEFT JOIN paper_orders p ON p.decision_id = d.id
                WHERE d.id = %s
                """,
                (decision_id,),
            )
            row = cursor.fetchone()
            if row is None:
                raise ValueError("Decision not found.")
            if row.get("paper_order_id") is None:
                raise ValueError("A realized trade outcome requires a submitted paper order.")

            premium = _float_or_none(row.get("premium_received"))
            close_cost = _float_or_none(closing_cost)
            pnl = _float_or_none(realized_pnl)
            if pnl is None and premium is not None and close_cost is not None:
                pnl = premium - close_cost
            retained = pnl / premium * 100 if pnl is not None and premium else None
            now = utc_now()
            cursor.execute(
                """
                INSERT INTO trade_outcomes (
                    id, decision_id, paper_order_id, contract_symbol, ticker_symbol,
                    status, outcome_label, premium_received, closing_cost,
                    realized_pnl, premium_retained_percent, assigned,
                    expired_worthless, opened_at, closed_at, notes,
                    raw_outcome, updated_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                          %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (decision_id) DO UPDATE SET
                    status = EXCLUDED.status,
                    outcome_label = EXCLUDED.outcome_label,
                    closing_cost = EXCLUDED.closing_cost,
                    realized_pnl = EXCLUDED.realized_pnl,
                    premium_retained_percent = EXCLUDED.premium_retained_percent,
                    assigned = EXCLUDED.assigned,
                    expired_worthless = EXCLUDED.expired_worthless,
                    closed_at = EXCLUDED.closed_at,
                    notes = EXCLUDED.notes,
                    raw_outcome = EXCLUDED.raw_outcome,
                    updated_at = EXCLUDED.updated_at
                RETURNING *
                """,
                (
                    str(uuid4()), decision_id, row["paper_order_id"],
                    row["contract_symbol"], row["ticker_symbol"], status,
                    outcome_label, premium, close_cost, pnl, retained, assigned,
                    expired_worthless, row.get("alpaca_submitted_at"),
                    now if status == "complete" else None, notes,
                    jsonb(raw_outcome or {}), now,
                ),
            )
            outcome = cursor.fetchone()
    return json_safe(outcome)


## Convert optional numeric request values to floats.
def _float_or_none(value):
    return None if value is None else float(value)
