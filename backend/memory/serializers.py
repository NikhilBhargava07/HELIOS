"""Convert Postgres rows and database types into API-ready dictionaries."""

from backend.memory.database import json_safe


def normalize_candidate(candidate):
    """Return the stable candidate fields persisted and exposed by the API."""
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
    """Convert a csp_candidates row into the frontend candidate shape."""
    candidate = normalize_candidate({
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
    })
    candidate.update(row.get("raw_candidate") or {})
    return json_safe(candidate)


def recommendation_from_row(row, candidates):
    """Combine a recommendation run row with its saved candidates."""
    return json_safe({
        "id": row["id"],
        "created_at": row["created_at"],
        "candidates": candidates,
        "agent_review": row["agent_review"],
    })


def decision_from_row(row):
    """Convert a user decision row into an API-safe dictionary."""
    return json_safe({
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
    })


def order_from_row(row):
    """Convert a paper order row into an API-safe dictionary."""
    return json_safe({
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
    })


def position_from_row(row):
    """Convert a locally tracked position row into an API-safe dictionary."""
    return json_safe({
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
    })
