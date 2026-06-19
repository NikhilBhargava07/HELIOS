import os
from threading import Lock
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import psycopg
from dotenv import load_dotenv
from psycopg.rows import dict_row


load_dotenv(Path(__file__).with_name(".env"))

DEFAULT_DATABASE_URL = "postgresql://csp_agent:csp_agent_dev_password@localhost:5432/csp_agent"
_schema_ready = False
_schema_lock = Lock()


def get_database_url():
    return os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)


def get_connection():
    return psycopg.connect(get_database_url(), row_factory=dict_row)


def json_safe(value):
    if isinstance(value, Decimal):
        return float(value)

    if isinstance(value, UUID):
        return str(value)

    if isinstance(value, (datetime, date)):
        return value.isoformat()

    if isinstance(value, list):
        return [json_safe(item) for item in value]

    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}

    return value


def utc_now():
    return datetime.now(timezone.utc)


def ensure_schema():
    global _schema_ready

    if _schema_ready:
        return

    with _schema_lock:
        if _schema_ready:
            return

        with get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS recommendation_runs (
                    id UUID PRIMARY KEY,
                    created_at TIMESTAMPTZ NOT NULL,
                    agent_review JSONB NOT NULL,
                    market_context JSONB,
                    strategy_rules JSONB
                );

                CREATE TABLE IF NOT EXISTS csp_candidates (
                    id UUID PRIMARY KEY,
                    recommendation_run_id UUID NOT NULL REFERENCES recommendation_runs(id) ON DELETE CASCADE,
                    contract_symbol TEXT NOT NULL,
                    ticker_symbol TEXT NOT NULL,
                    company_name TEXT,
                    expiration DATE NOT NULL,
                    dte INTEGER NOT NULL,
                    strike NUMERIC(12, 2) NOT NULL,
                    current_stock_price NUMERIC(12, 2),
                    delta NUMERIC(8, 4),
                    iv_percent NUMERIC(8, 4),
                    spread NUMERIC(12, 4),
                    premium_if_sold_at_bid NUMERIC(12, 2),
                    cash_required NUMERIC(14, 2),
                    breakeven_price NUMERIC(12, 2),
                    return_on_cash_percent NUMERIC(8, 4),
                    raw_candidate JSONB NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );

                CREATE TABLE IF NOT EXISTS user_decisions (
                    id UUID PRIMARY KEY,
                    recommendation_run_id UUID NOT NULL REFERENCES recommendation_runs(id) ON DELETE CASCADE,
                    contract_symbol TEXT NOT NULL,
                    ticker_symbol TEXT NOT NULL,
                    action TEXT NOT NULL,
                    note TEXT,
                    agent_selected_contract TEXT,
                    agent_decision TEXT,
                    alpaca_order_id TEXT,
                    order_error TEXT,
                    created_at TIMESTAMPTZ NOT NULL
                );

                CREATE TABLE IF NOT EXISTS paper_orders (
                    id UUID PRIMARY KEY,
                    decision_id UUID NOT NULL REFERENCES user_decisions(id) ON DELETE CASCADE,
                    status TEXT NOT NULL,
                    side TEXT NOT NULL,
                    strategy TEXT NOT NULL,
                    contract_symbol TEXT NOT NULL,
                    ticker_symbol TEXT NOT NULL,
                    expiration DATE NOT NULL,
                    strike NUMERIC(12, 2) NOT NULL,
                    premium_received NUMERIC(12, 2) NOT NULL,
                    cash_required NUMERIC(14, 2) NOT NULL,
                    breakeven_price NUMERIC(12, 2),
                    alpaca_order_id TEXT,
                    alpaca_client_order_id TEXT,
                    alpaca_limit_price NUMERIC(12, 2),
                    alpaca_submitted_at TIMESTAMPTZ,
                    raw_alpaca_order JSONB,
                    created_at TIMESTAMPTZ NOT NULL
                );

                CREATE TABLE IF NOT EXISTS positions (
                    id UUID PRIMARY KEY,
                    order_id UUID NOT NULL REFERENCES paper_orders(id) ON DELETE CASCADE,
                    status TEXT NOT NULL,
                    strategy TEXT NOT NULL,
                    contract_symbol TEXT NOT NULL,
                    ticker_symbol TEXT NOT NULL,
                    expiration DATE NOT NULL,
                    strike NUMERIC(12, 2) NOT NULL,
                    premium_received NUMERIC(12, 2) NOT NULL,
                    cash_required NUMERIC(14, 2) NOT NULL,
                    breakeven_price NUMERIC(12, 2),
                    realized_pnl NUMERIC(14, 2) NOT NULL DEFAULT 0,
                    opened_at TIMESTAMPTZ NOT NULL,
                    closed_at TIMESTAMPTZ
                );

                CREATE INDEX IF NOT EXISTS idx_csp_candidates_ticker_created
                    ON csp_candidates(ticker_symbol, created_at DESC);

                CREATE INDEX IF NOT EXISTS idx_csp_candidates_run_created
                    ON csp_candidates(recommendation_run_id, created_at ASC);

                CREATE INDEX IF NOT EXISTS idx_user_decisions_ticker_created
                    ON user_decisions(ticker_symbol, created_at DESC);

                CREATE INDEX IF NOT EXISTS idx_positions_status
                    ON positions(status);


                CREATE INDEX IF NOT EXISTS idx_paper_orders_created
                    ON paper_orders(created_at DESC);

                CREATE INDEX IF NOT EXISTS idx_recommendation_runs_created
                    ON recommendation_runs(created_at DESC);
                """
            )
                cursor.execute("ALTER TABLE user_decisions ADD COLUMN IF NOT EXISTS alpaca_order_id TEXT;")
                cursor.execute("ALTER TABLE user_decisions ADD COLUMN IF NOT EXISTS order_error TEXT;")
                cursor.execute("ALTER TABLE paper_orders ADD COLUMN IF NOT EXISTS alpaca_order_id TEXT;")
                cursor.execute("ALTER TABLE paper_orders ADD COLUMN IF NOT EXISTS alpaca_client_order_id TEXT;")
                cursor.execute("ALTER TABLE paper_orders ADD COLUMN IF NOT EXISTS alpaca_limit_price NUMERIC(12, 2);")
                cursor.execute("ALTER TABLE paper_orders ADD COLUMN IF NOT EXISTS alpaca_submitted_at TIMESTAMPTZ;")
                cursor.execute("ALTER TABLE paper_orders ADD COLUMN IF NOT EXISTS raw_alpaca_order JSONB;")

        _schema_ready = True
