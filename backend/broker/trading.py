## Read Alpaca paper-account state and submit option paper orders.

import hashlib
import re

from alpaca.data.enums import OptionsFeed
from alpaca.data.requests import OptionLatestQuoteRequest
from alpaca.trading.client import TradingClient
from alpaca.trading.enums import (
    OrderClass,
    OrderSide,
    PositionIntent,
    QueryOrderStatus,
    TimeInForce,
)
from alpaca.trading.requests import GetOrdersRequest, LimitOrderRequest

from backend.config import SHARES_PER_CONTRACT

OPTION_SYMBOL_PATTERN = re.compile(
    r"^(?P<ticker>[A-Z.]+)(?P<expiration>\d{6})(?P<type>[CP])(?P<strike>\d{8})$"
)
OPTION_LIFECYCLE_ACTIVITY_TYPES = ("OPASN", "OPEXP", "OPCSH")


## Create an Alpaca paper-trading client from explicit credentials.
## This is the user-specific path HELIOS will use after profile onboarding stores broker keys per Cognito user.
def create_trading_client(api_key, secret_key):
    return TradingClient(api_key, secret_key, paper=True)


## Require callers to pass an explicit trading client.
## This prevents old APCA/ALPACA env keys from being used silently when a signed-in user has not connected broker credentials.
def require_trading_client(trading_client):
    if trading_client is None:
        raise ValueError("Explicit Alpaca trading client required. Connect a user broker profile first.")
    return trading_client


## Validate a user-supplied Alpaca paper credential pair with a read-only account call.
## Signup/onboarding uses this before saving anything so fake or mismatched broker keys do not become a HELIOS profile.
def validate_alpaca_paper_credentials(api_key, secret_key):
    account = create_trading_client(api_key, secret_key).get_account()
    raw_account = serialize_alpaca_model(account)

    return {
        "account_id": raw_account.get("id"),
        "account_number": raw_account.get("account_number"),
        "status": str(raw_account.get("status")),
        "currency": raw_account.get("currency"),
        "cash": number_or_none(raw_account.get("cash")),
        "portfolio_value": first_number(raw_account, "portfolio_value", "equity", "cash"),
        "equity": first_number(raw_account, "equity"),
    }


## Choose a conservative limit credit for selling one option contract.
## HELIOS starts from the candidate bid/premium data because a recommendation should assume the user receives a real quoted credit.
def option_limit_price_from_candidate(candidate):
    premium_total = candidate.get("premiumIfSoldAtBid")

    if premium_total is None:
        raise ValueError("Candidate is missing premiumIfSoldAtBid.")

    # Alpaca option limit orders use per-share option premium, not total contract premium.
    return round(float(premium_total) / SHARES_PER_CONTRACT, 2)


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
def get_paper_account_summary(trading_client=None):
    trading_client = require_trading_client(trading_client)
    account = trading_client.get_account()
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
## Alpaca positions and orders use compact symbols, so parsing them lets HELIOS read the contract behind either one.
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
## Any sold contract records the premium it collected, while cash required and breakeven stay put-specific:
## a covered call locks up no cash, and its breakeven depends on what the shares cost, which one position cannot say.
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
        is_short = quantity is not None and quantity < 0
        is_short_put = contract["option_type"] == "put" and is_short
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
            "premium_received": average_premium * SHARES_PER_CONTRACT * contract_count if is_short else None,
            "cash_required": strike * SHARES_PER_CONTRACT * contract_count if is_short_put else 0,
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
def get_paper_positions(trading_client=None):
    trading_client = require_trading_client(trading_client)
    return [
        normalize_paper_position(serialize_alpaca_model(model))
        for model in trading_client.get_all_positions()
    ]


## Fetch recent Alpaca paper orders for reconciliation.
## Canceled orders are later filtered from display, while active/filled orders keep HELIOS memory aligned with the broker.
def get_paper_orders(limit=100, trading_client=None):
    trading_client = require_trading_client(trading_client)
    request = GetOrdersRequest(status=QueryOrderStatus.ALL, limit=limit)
    return [
        normalize_paper_order(serialize_alpaca_model(order))
        for order in trading_client.get_orders(filter=request)
    ]


## Fetch option assignment, expiration, and cash-settlement evidence from Alpaca.
## Paper option activities can arrive after positions change, so outcome finalization polls these REST records instead of treating a missing position as proof of assignment or expiration.
def get_option_lifecycle_activities(
    after=None,
    trading_client=None,
    activity_types=OPTION_LIFECYCLE_ACTIVITY_TYPES,
):
    trading_client = require_trading_client(trading_client)
    activities = []
    errors = []
    query = {"direction": "desc", "page_size": 100}
    if after:
        query["after"] = after

    for activity_type in activity_types:
        try:
            response = trading_client.get(
                f"/account/activities/{activity_type}",
                query,
            )
        except Exception as error:
            errors.append(error)
            continue
        for activity in response or []:
            normalized = dict(activity)
            raw_type = normalized.get("activity_type") or activity_type
            normalized["activity_type"] = str(
                getattr(raw_type, "value", raw_type)
            ).upper()
            activities.append(normalized)

    if errors and len(errors) == len(activity_types):
        raise errors[0]
    return activities


## Convert an Alpaca order into the stable lifecycle shape saved by HELIOS.
## Fill quantities, prices, and terminal timestamps are retained for reconciliation and later outcome learning.
def normalize_paper_order(raw_order):
    return {
        field: raw_order.get(field)
        for field in (
            "id",
            "client_order_id",
            "status",
            "symbol",
            "side",
            "type",
            "time_in_force",
            "position_intent",
            "limit_price",
            "qty",
            "filled_qty",
            "filled_avg_price",
            "submitted_at",
            "updated_at",
            "filled_at",
            "canceled_at",
            "expired_at",
            "failed_at",
        )
    }


## Derive a repeatable, opaque Alpaca client order id from one user action target.
## A browser retry for the same recommendation and contract therefore cannot create a second sell order.
def build_helios_client_order_id(user_id, run_id, contract_symbol):
    digest = hashlib.sha256(
        f"{user_id}|{run_id}|{contract_symbol}".encode("utf-8")
    ).hexdigest()[:32]
    return f"helios-{digest}"


## Re-fetch the exact option quote immediately before an order is submitted.
## This prevents HELIOS from placing a limit order from an old scan when the bid, spread, or displayed liquidity has changed materially.
def refresh_candidate_option_quote(
    candidate,
    option_data_client,
    strategy,
    economics,
):
    contract_symbol = candidate["contractSymbol"]
    max_spread = strategy.rules.max_spread
    min_quote_size = strategy.rules.min_quote_size
    request = OptionLatestQuoteRequest(
        symbol_or_symbols=contract_symbol,
        feed=OptionsFeed.INDICATIVE,
    )
    latest_quotes = option_data_client.get_option_latest_quote(request)
    quote_model = latest_quotes.get(contract_symbol)
    if quote_model is None:
        raise ValueError(
            f"The latest option quote is unavailable. Run a new scan before placing this {strategy.short_label}."
        )

    quote = serialize_alpaca_model(quote_model)
    bid = number_or_none(quote.get("bid_price"))
    ask = number_or_none(quote.get("ask_price"))
    bid_size = number_or_none(quote.get("bid_size")) or 0
    ask_size = number_or_none(quote.get("ask_size")) or 0
    if bid is None or ask is None or bid <= 0 or ask <= 0 or ask < bid:
        raise ValueError(
            f"The latest option bid/ask quote is not usable. Run a new scan before placing this {strategy.short_label}."
        )

    spread = ask - bid
    if spread > max_spread:
        raise ValueError(
            f"The option spread widened to ${spread:.2f}, above the ${max_spread:.2f} strategy limit."
        )
    if bid_size < min_quote_size or ask_size < min_quote_size:
        raise ValueError("The latest option quote no longer meets the liquidity rule.")

    refreshed = dict(candidate)
    refreshed.update({
        "bid": bid,
        "ask": ask,
        "spread": spread,
        "bidSize": int(bid_size),
        "askSize": int(ask_size),
        "quoteCheckedAt": str(quote.get("timestamp") or ""),
    })

    # The strategy reprices the contract from the quote it would actually be sold at, and against
    # the collateral just verified, so every number shown agrees with the order being submitted.
    # Only fields the candidate already carries are replaced, since each strategy displays its own.
    repriced = economics(
        strike=float(candidate["strike"]),
        bid=bid,
        current_stock_price=float(candidate["currentStockPrice"]),
        dte=int(candidate["DTE"]),
    )
    refreshed.update({
        column: value for column, value in repriced.items() if column in candidate
    })
    return refreshed


## Submit a one-contract sell-to-open option limit order to Alpaca paper trading.
## Selling to open exactly one contract is the only shape HELIOS supports, so the collateral checked
## before this call is the whole obligation and the prototype cannot place arbitrary trade types.
def submit_sell_to_open_option_order(
    candidate,
    trading_client=None,
    client_order_id=None,
):
    trading_client = require_trading_client(trading_client)
    contract_symbol = candidate["contractSymbol"]
    limit_price = option_limit_price_from_candidate(candidate)
    if not client_order_id:
        raise ValueError("A deterministic HELIOS client order id is required.")

    order_request = LimitOrderRequest(
        symbol=contract_symbol,
        qty=1,
        side=OrderSide.SELL,
        time_in_force=TimeInForce.DAY,
        limit_price=limit_price,
        order_class=OrderClass.SIMPLE,
        position_intent=PositionIntent.SELL_TO_OPEN,
        client_order_id=client_order_id,
    )

    order = trading_client.submit_order(order_request)
    serialized_order = serialize_alpaca_model(order)

    normalized = normalize_paper_order(serialized_order)
    normalized["symbol"] = normalized.get("symbol") or contract_symbol
    normalized["limit_price"] = normalized.get("limit_price") or limit_price
    normalized["qty"] = normalized.get("qty") or "1"
    return normalized
