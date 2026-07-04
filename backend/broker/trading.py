## Read Alpaca paper-account state and submit CSP paper orders.

import re
from functools import lru_cache
from uuid import uuid4

from alpaca.trading.client import TradingClient
from alpaca.trading.enums import (
    OrderClass,
    OrderSide,
    PositionIntent,
    QueryOrderStatus,
    TimeInForce,
)
from alpaca.trading.requests import GetOrdersRequest, LimitOrderRequest
from backend.broker.clients import get_alpaca_credentials

OPTION_SYMBOL_PATTERN = re.compile(
    r"^(?P<ticker>[A-Z.]+)(?P<expiration>\d{6})(?P<type>[CP])(?P<strike>\d{8})$"
)


## Create an Alpaca paper-trading client from explicit credentials.
## This is the user-specific path HELIOS will use after profile onboarding stores broker keys per Cognito user.
def create_trading_client(api_key, secret_key):
    return TradingClient(api_key, secret_key, paper=True)


## Create a cached authenticated client pinned to Alpaca paper trading.
@lru_cache(maxsize=1)
## Create an Alpaca trading client connected to the configured paper account.
## All account, order, and position actions go through this helper so credentials and paper/live mode remain centralized.
def get_trading_client():
    api_key, secret_key = get_alpaca_credentials()

    return create_trading_client(api_key, secret_key)


## Choose a conservative limit credit for selling one put contract.
## HELIOS starts from the candidate bid/premium data because CSP recommendations should assume the user receives a real quoted credit.
def option_limit_price_from_candidate(candidate):
    premium_total = candidate.get("premiumIfSoldAtBid")

    if premium_total is None:
        raise ValueError("Candidate is missing premiumIfSoldAtBid.")

    # Alpaca option limit orders use per-share option premium, not total contract premium.
    return round(float(premium_total) / 100, 2)


## Convert Alpaca SDK models into plain dictionaries.
## Normalizing SDK objects makes later parsing predictable and keeps API responses JSON-friendly.
def serialize_alpaca_model(model):
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")

    if hasattr(model, "dict"):
        return model.dict()

    return dict(model)


## Safely parse broker numeric fields that may arrive as strings or missing values.
## Alpaca often returns decimals as strings, so this helper keeps calculations from crashing on blanks.
def number_or_none(value):
    if value is None:
        return None

    try:
        return float(value)
    except (TypeError, ValueError):
        return None


## Return the first parseable number from several possible broker fields.
## This is used when Alpaca may expose the same account value under different field names.
def first_number(raw_data, *keys):
    for key in keys:
        value = raw_data.get(key)
        number = number_or_none(value)

        if number is not None:
            return number

    return None


## Read live paper-account balances and buying power from Alpaca.
## The resulting summary drives effective CSP cash, dashboard totals, and pre-trade affordability checks.
def get_paper_account_summary():
    account = get_trading_client().get_account()
    raw_account = serialize_alpaca_model(account)
    buying_power = first_number(
        raw_account,
        "options_buying_power",
        "buying_power",
        "cash",
    )
    cash = first_number(raw_account, "cash")
    portfolio_value = first_number(raw_account, "portfolio_value", "equity", "cash")

    return {
        "cash": cash,
        "buying_power": first_number(raw_account, "buying_power"),
        "options_buying_power": first_number(raw_account, "options_buying_power"),
        "available_csp_cash": buying_power,
        "portfolio_value": portfolio_value,
        "equity": first_number(raw_account, "equity"),
        "last_equity": first_number(raw_account, "last_equity"),
        "long_market_value": first_number(raw_account, "long_market_value"),
        "short_market_value": first_number(raw_account, "short_market_value"),
    }


## Decode an OCC-style option symbol into ticker, expiration, type, and strike.
## Alpaca positions use compact symbols, so parsing them lets the UI display readable CSP details.
def parse_option_contract_symbol(contract_symbol):
    match = OPTION_SYMBOL_PATTERN.match(contract_symbol or "")

    if not match:
        return None

    expiration_code = match.group("expiration")

    return {
        "ticker_symbol": match.group("ticker"),
        "expiration": f"20{expiration_code[:2]}-{expiration_code[2:4]}-{expiration_code[4:]}",
        "option_type": "put" if match.group("type") == "P" else "call",
        "strike": int(match.group("strike")) / 1000,
    }


## Convert one Alpaca position into the shape HELIOS displays and reasons over.
## Short puts become CSP records with cash required, breakeven, premium estimate, and unrealized P&L; other holdings stay as general positions.
def normalize_paper_position(raw_position):
    symbol = raw_position.get("symbol")
    quantity = number_or_none(raw_position.get("qty"))
    contract = parse_option_contract_symbol(symbol)
    asset_class = raw_position.get("asset_class") or ("option" if contract else "stock")
    average_entry_price = number_or_none(raw_position.get("avg_entry_price"))

    if contract:
        contract_count = abs(quantity or 0)
        average_premium = average_entry_price or 0
        strike = contract["strike"]
        is_short_put = contract["option_type"] == "put" and quantity is not None and quantity < 0
        return {
            "id": str(raw_position.get("asset_id") or symbol),
            "status": "open",
            "source": "alpaca",
            "asset_class": "option",
            "strategy": "cash-secured put" if is_short_put else f"{contract['option_type']} option",
            "contract_symbol": symbol,
            "ticker_symbol": contract["ticker_symbol"],
            "expiration": contract["expiration"],
            "option_type": contract["option_type"],
            "strike": strike,
            "quantity": contract_count,
            "signed_quantity": quantity,
            "premium_received": average_premium * 100 * contract_count if is_short_put else None,
            "cash_required": strike * 100 * contract_count if is_short_put else 0,
            "breakeven_price": strike - average_premium if is_short_put else None,
            "market_value": number_or_none(raw_position.get("market_value")),
            "unrealized_pnl": number_or_none(raw_position.get("unrealized_pl")),
            "current_price": number_or_none(raw_position.get("current_price")),
            "average_entry_price": average_entry_price,
        }

    return {
        "id": str(raw_position.get("asset_id") or symbol),
        "status": "open",
        "source": "alpaca",
        "asset_class": asset_class,
        "strategy": "stock",
        "symbol": symbol,
        "ticker_symbol": symbol,
        "quantity": quantity,
        "market_value": number_or_none(raw_position.get("market_value")),
        "unrealized_pnl": number_or_none(raw_position.get("unrealized_pl")),
        "current_price": number_or_none(raw_position.get("current_price")),
        "average_entry_price": average_entry_price,
    }


## Fetch and normalize all open positions from the Alpaca paper account.
## The dashboard relies on this live broker view rather than stale local memory whenever possible.
def get_paper_positions():
    return [
        normalize_paper_position(serialize_alpaca_model(model))
        for model in get_trading_client().get_all_positions()
    ]


## Fetch recent Alpaca paper orders for reconciliation.
## Canceled orders are later filtered from display, while active/filled orders keep HELIOS memory aligned with the broker.
def get_paper_orders(limit=500):
    request = GetOrdersRequest(status=QueryOrderStatus.ALL, limit=limit)
    return [
        serialize_alpaca_model(order)
        for order in get_trading_client().get_orders(filter=request)
    ]


## Submit a one-contract sell-to-open put limit order to Alpaca paper trading.
## The function intentionally supports only the recommended CSP flow so the prototype cannot place arbitrary trade types.
def submit_cash_secured_put_order(candidate):
    trading_client = get_trading_client()
    contract_symbol = candidate["contractSymbol"]
    limit_price = option_limit_price_from_candidate(candidate)

    order_request = LimitOrderRequest(
        symbol=contract_symbol,
        qty=1,
        side=OrderSide.SELL,
        time_in_force=TimeInForce.DAY,
        limit_price=limit_price,
        order_class=OrderClass.SIMPLE,
        position_intent=PositionIntent.SELL_TO_OPEN,
        client_order_id=f"helios-{uuid4().hex[:24]}",
    )

    order = trading_client.submit_order(order_request)
    serialized_order = serialize_alpaca_model(order)

    return {
        "id": serialized_order.get("id"),
        "client_order_id": serialized_order.get("client_order_id"),
        "status": serialized_order.get("status"),
        "symbol": serialized_order.get("symbol", contract_symbol),
        "side": serialized_order.get("side"),
        "type": serialized_order.get("type"),
        "time_in_force": serialized_order.get("time_in_force"),
        "limit_price": serialized_order.get("limit_price", limit_price),
        "qty": serialized_order.get("qty", "1"),
        "submitted_at": serialized_order.get("submitted_at"),
        "raw_order": serialized_order,
    }
