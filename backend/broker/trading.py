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


## Create a cached authenticated client pinned to Alpaca paper trading.
@lru_cache(maxsize=1)
def get_trading_client():
    api_key, secret_key = get_alpaca_credentials()

    return TradingClient(api_key, secret_key, paper=True)


## Convert total contract premium into Alpaca's per-share limit price.
def option_limit_price_from_candidate(candidate):
    premium_total = candidate.get("premiumIfSoldAtBid")

    if premium_total is None:
        raise ValueError("Candidate is missing premiumIfSoldAtBid.")

    # Alpaca option limit orders use per-share option premium, not total contract premium.
    return round(float(premium_total) / 100, 2)


## Convert an Alpaca SDK model into a JSON-compatible dictionary.
def serialize_alpaca_model(model):
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")

    if hasattr(model, "dict"):
        return model.dict()

    return dict(model)


## Parse a numeric broker field without raising on absent values.
def number_or_none(value):
    if value is None:
        return None

    try:
        return float(value)
    except (TypeError, ValueError):
        return None


## Return the first numeric value found among ordered account keys.
def first_number(raw_data, *keys):
    for key in keys:
        value = raw_data.get(key)
        number = number_or_none(value)

        if number is not None:
            return number

    return None


## Return the paper account fields needed for portfolio and CSP buying-power checks.
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


## Parse an OCC option symbol into ticker, expiration, type, and strike.
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


## Convert one Alpaca position into a display-safe portfolio record.
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


## Return every open Alpaca paper position, including stocks and options.
def get_paper_positions():
    return [
        normalize_paper_position(serialize_alpaca_model(model))
        for model in get_trading_client().get_all_positions()
    ]


## Return normalized short-put positions from the Alpaca paper account.
def get_paper_csp_positions():
    return [
        position for position in get_paper_positions()
        if position.get("strategy") == "cash-secured put" and position.get("signed_quantity", 0) < 0
    ]


## Return recent open and closed Alpaca paper orders for reconciliation.
def get_paper_orders(limit=500):
    request = GetOrdersRequest(status=QueryOrderStatus.ALL, limit=limit)
    return [
        serialize_alpaca_model(order)
        for order in get_trading_client().get_orders(filter=request)
    ]


## Submit one sell-to-open CSP limit order to Alpaca paper trading.
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
