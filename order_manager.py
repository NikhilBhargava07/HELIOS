import os
from pathlib import Path
from uuid import uuid4

from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderClass, OrderSide, PositionIntent, TimeInForce
from alpaca.trading.requests import LimitOrderRequest
from dotenv import load_dotenv


load_dotenv(Path(__file__).with_name(".env"))


def get_alpaca_credentials():
    api_key = os.getenv("APCA_API_KEY_ID") or os.getenv("ALPACA_API_KEY")
    secret_key = os.getenv("APCA_API_SECRET_KEY") or os.getenv("ALPACA_SECRET_KEY")

    if not api_key or not secret_key:
        raise ValueError("Missing Alpaca API credentials in .env")

    return api_key, secret_key


def get_trading_client():
    api_key, secret_key = get_alpaca_credentials()

    return TradingClient(api_key, secret_key, paper=True)


def option_limit_price_from_candidate(candidate):
    premium_total = candidate.get("premiumIfSoldAtBid")

    if premium_total is None:
        raise ValueError("Candidate is missing premiumIfSoldAtBid.")

    # Alpaca option limit orders use per-share option premium, not total contract premium.
    return round(float(premium_total) / 100, 2)


def serialize_alpaca_order(order):
    if hasattr(order, "model_dump"):
        return order.model_dump(mode="json")

    if hasattr(order, "dict"):
        return order.dict()

    return dict(order)


def serialize_alpaca_model(model):
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")

    if hasattr(model, "dict"):
        return model.dict()

    return dict(model)


def number_or_none(value):
    if value is None:
        return None

    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def first_number(raw_data, *keys):
    for key in keys:
        value = raw_data.get(key)
        number = number_or_none(value)

        if number is not None:
            return number

    return None


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

    return {
        "id": raw_account.get("id"),
        "status": raw_account.get("status"),
        "currency": raw_account.get("currency"),
        "cash": cash,
        "buying_power": first_number(raw_account, "buying_power"),
        "options_buying_power": first_number(raw_account, "options_buying_power"),
        "available_csp_cash": buying_power,
    }


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
        client_order_id=f"csp-agent-{uuid4().hex[:24]}",
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
