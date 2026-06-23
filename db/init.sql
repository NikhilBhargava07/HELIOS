CREATE TABLE IF NOT EXISTS recommendation_runs (
    id UUID PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL,
    agent_review JSONB NOT NULL,
    market_context JSONB,
    strategy_rules JSONB,
    portfolio_context JSONB,
    memory_context JSONB
);

ALTER TABLE recommendation_runs
    ADD COLUMN IF NOT EXISTS market_context JSONB,
    ADD COLUMN IF NOT EXISTS strategy_rules JSONB,
    ADD COLUMN IF NOT EXISTS portfolio_context JSONB,
    ADD COLUMN IF NOT EXISTS memory_context JSONB;

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

CREATE TABLE IF NOT EXISTS candidate_observations (
    id UUID PRIMARY KEY,
    candidate_id UUID NOT NULL REFERENCES csp_candidates(id) ON DELETE CASCADE,
    recommendation_run_id UUID NOT NULL REFERENCES recommendation_runs(id) ON DELETE CASCADE,
    contract_symbol TEXT NOT NULL,
    ticker_symbol TEXT NOT NULL,
    horizon_days INTEGER NOT NULL,
    observed_at TIMESTAMPTZ NOT NULL,
    stock_price NUMERIC(12, 4),
    stock_return_percent NUMERIC(10, 4),
    option_bid NUMERIC(12, 4),
    option_ask NUMERIC(12, 4),
    option_mark NUMERIC(12, 4),
    estimated_close_cost NUMERIC(14, 2),
    estimated_pnl NUMERIC(14, 2),
    premium_retained_percent NUMERIC(10, 4),
    price_zone TEXT NOT NULL,
    raw_snapshot JSONB,
    UNIQUE(candidate_id, horizon_days)
);

CREATE TABLE IF NOT EXISTS trade_outcomes (
    id UUID PRIMARY KEY,
    decision_id UUID NOT NULL UNIQUE REFERENCES user_decisions(id) ON DELETE CASCADE,
    paper_order_id UUID REFERENCES paper_orders(id) ON DELETE SET NULL,
    contract_symbol TEXT NOT NULL,
    ticker_symbol TEXT NOT NULL,
    status TEXT NOT NULL,
    outcome_label TEXT NOT NULL,
    premium_received NUMERIC(14, 2),
    closing_cost NUMERIC(14, 2),
    realized_pnl NUMERIC(14, 2),
    premium_retained_percent NUMERIC(10, 4),
    assigned BOOLEAN,
    expired_worthless BOOLEAN,
    opened_at TIMESTAMPTZ,
    closed_at TIMESTAMPTZ,
    notes TEXT,
    raw_outcome JSONB,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS user_profile_versions (
    id UUID PRIMARY KEY,
    generated_at TIMESTAMPTZ NOT NULL,
    evidence_count INTEGER NOT NULL,
    confidence TEXT NOT NULL,
    profile JSONB NOT NULL,
    fingerprint TEXT NOT NULL UNIQUE
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

CREATE INDEX IF NOT EXISTS idx_candidate_observations_ticker_horizon
    ON candidate_observations(ticker_symbol, horizon_days, observed_at DESC);

CREATE INDEX IF NOT EXISTS idx_trade_outcomes_ticker_updated
    ON trade_outcomes(ticker_symbol, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_user_profile_versions_generated
    ON user_profile_versions(generated_at DESC);
