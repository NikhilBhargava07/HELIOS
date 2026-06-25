## Read Alpaca paper-account state and submit CSP paper orders.

import re
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


def get_trading_client():
    ## Create an authenticated client pinned to Alpaca paper trading.
    api_key, secret_key = get_alpaca_credentials()

    return TradingClient(api_key, secret_key, paper=True)


def option_limit_price_from_candidate(candidate):
    ## Convert total contract premium into Alpaca's per-share limit price.
    premium_total = candidate.get("premiumIfSoldAtBid")

    if premium_total is None:
        raise ValueError("Candidate is missing premiumIfSoldAtBid.")

    # Alpaca option limit orders use per-share option premium, not total contract premium.
    return round(float(premium_total) / 100, 2)


def serialize_alpaca_order(order):
    ## Convert an Alpaca order model into a JSON-compatible dictionary.
    if hasattr(order, "model_dump"):
        return order.model_dump(mode="json")

    if hasattr(order, "dict"):
        return order.dict()

    return dict(order)


def serialize_alpaca_model(model):
    ## Convert a general Alpaca SDK model into a dictionary.
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")

    if hasattr(model, "dict"):
        return model.dict()

    return dict(model)


def number_or_none(value):
    ## Parse a numeric broker field without raising on absent values.
    if value is None:
        return None

    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def first_number(raw_data, *keys):
    ## Return the first numeric value found among ordered account keys.
    for key in keys:
        value = raw_data.get(key)
        number = number_or_none(value)

        if number is not None:
            return number

    return None


def get_paper_account_summary():
    ## Return the paper account fields needed for CSP buying-power checks.
    account = get_trading_client().get_account()
    raw_account = serialize_alpaca_model(account)
    buying_power = first_number(
        raw_account,
        "options_buying_power",
        "buying_power",
        "cash",
    )
    cash = first_number(raw_account, "cash")

    return {
        "cash": cash,
        "buying_power": first_number(raw_account, "buying_power"),
        "options_buying_power": first_number(raw_account, "options_buying_power"),
        "available_csp_cash": buying_power,
    }


def parse_option_contract_symbol(contract_symbol):
    ## Parse an OCC option symbol into ticker, expiration, type, and strike.
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


def get_paper_csp_positions():
    ## Return normalized short-put positions from the Alpaca paper account.
    positions = []

    for model in get_trading_client().get_all_positions():
        raw_position = serialize_alpaca_model(model)
        contract_symbol = raw_position.get("symbol")
        contract = parse_option_contract_symbol(contract_symbol)
        quantity = number_or_none(raw_position.get("qty"))

        if not contract or contract["option_type"] != "put" or quantity is None or quantity >= 0:
            continue

        contract_count = abs(quantity)
        average_premium = number_or_none(raw_position.get("avg_entry_price")) or 0
        strike = contract["strike"]

        positions.append(
            {
                "id": str(raw_position.get("asset_id") or contract_symbol),
                "status": "open",
                "source": "alpaca",
                "strategy": "cash-secured put",
                "contract_symbol": contract_symbol,
                "ticker_symbol": contract["ticker_symbol"],
                "expiration": contract["expiration"],
                "strike": strike,
                "quantity": contract_count,
                "premium_received": average_premium * 100 * contract_count,
                "cash_required": strike * 100 * contract_count,
                "breakeven_price": strike - average_premium,
                "market_value": number_or_none(raw_position.get("market_value")),
                "unrealized_pnl": number_or_none(raw_position.get("unrealized_pl")),
            }
        )

    return positions


def get_paper_orders(limit=500):
    ## Return recent open and closed Alpaca paper orders for reconciliation.
    request = GetOrdersRequest(status=QueryOrderStatus.ALL, limit=limit)
    return [
        serialize_alpaca_order(order)
        for order in get_trading_client().get_orders(filter=request)
    ]


def submit_cash_secured_put_order(candidate):
    ## Submit one sell-to-open CSP limit order to Alpaca paper trading.
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
    serialized_order = serialize_alpaca_order(order)

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
