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

CREATE INDEX IF NOT EXISTS idx_user_decisions_ticker_created
    ON user_decisions(ticker_symbol, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_positions_status
    ON positions(status);
