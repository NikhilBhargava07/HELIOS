## Record user decisions and reconcile paper orders in DynamoDB.

from uuid import uuid4

from backend.memory.dynamodb_store import (
    get_item,
    put_item,
    put_items,
    query_items,
    user_pk,
    utc_now_text,
)
from backend.memory.outcome_analysis import number_or_none
from backend.memory.recommendations import (
    find_candidate,
    get_recommendation_run,
)
from backend.broker.trading import parse_option_contract_symbol

FILLED_ORDER_STATUSES = {"filled"}
ORDER_LIFECYCLE_FIELDS = (
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


## Replace quoted economics with actual broker fill economics once Alpaca reports a fill.
## The original recommendation quote remains available for later slippage and execution-quality analysis.
def _apply_fill_economics(order):
    filled_price = number_or_none(order.get("alpaca_filled_avg_price"))
    filled_quantity = number_or_none(order.get("alpaca_filled_qty"))
    if filled_price is None or not filled_quantity or filled_quantity <= 0:
        return order

    strike = float(order["strike"])
    order["premium_received"] = filled_price * 100 * filled_quantity
    order["cash_required"] = strike * 100 * filled_quantity
    order["breakeven_price"] = strike - filled_price
    return order


## Convert a broker submission into the normalized HELIOS paper-order record.
## Only fields used by the dashboard and learning system are retained; the full Alpaca payload is deliberately omitted.
def _create_paper_order(decision, candidate, alpaca_order=None):
    alpaca_order = alpaca_order or {}
    order = {
        "id": str(uuid4()),
        "created_at": utc_now_text(),
        "decision_id": decision["id"],
        "recommendation_run_id": decision["recommendation_run_id"],
        "status": alpaca_order.get("status", "local_recorded"),
        "side": "sell",
        "strategy": "cash-secured put",
        "contract_symbol": candidate["contractSymbol"],
        "ticker_symbol": candidate["tickerSymbol"],
        "expiration": candidate["expiration"],
        "strike": candidate["strike"],
        "quoted_premium": candidate["premiumIfSoldAtBid"],
        "premium_received": candidate["premiumIfSoldAtBid"],
        "cash_required": candidate["cashRequired"],
        "breakeven_price": candidate["breakevenPrice"],
        "alpaca_order_id": alpaca_order.get("id"),
        "alpaca_client_order_id": alpaca_order.get("client_order_id"),
        "alpaca_limit_price": alpaca_order.get("limit_price"),
        "alpaca_submitted_at": alpaca_order.get("submitted_at"),
        "alpaca_updated_at": alpaca_order.get("updated_at"),
        "alpaca_qty": alpaca_order.get("qty"),
        "alpaca_filled_qty": alpaca_order.get("filled_qty"),
        "alpaca_filled_avg_price": alpaca_order.get("filled_avg_price"),
        "alpaca_filled_at": alpaca_order.get("filled_at"),
        "alpaca_canceled_at": alpaca_order.get("canceled_at"),
        "alpaca_expired_at": alpaca_order.get("expired_at"),
        "alpaca_failed_at": alpaca_order.get("failed_at"),
        "entry_factors": {
            "dte": candidate.get("DTE"),
            "delta": candidate.get("delta"),
            "iv_percent": candidate.get("ivPercent"),
            "spread": candidate.get("spread"),
            "return_on_cash_percent": candidate.get("returnOnCashPercent"),
            "stock_price": candidate.get("currentStockPrice"),
        },
    }
    return _apply_fill_economics(order)


## Build a fallback open-position record after a filled paper order.
## Live Alpaca positions remain authoritative; this record is used only when the broker position endpoint is unavailable.
def _create_open_position(order):
    filled_quantity = number_or_none(order.get("alpaca_filled_qty"))
    quantity = filled_quantity if filled_quantity and filled_quantity > 0 else 1
    filled_price = number_or_none(order.get("alpaca_filled_avg_price"))
    strike = float(order["strike"])
    premium_received = (
        filled_price * 100 * quantity
        if filled_price is not None
        else float(order["premium_received"])
    )
    breakeven_price = (
        strike - filled_price
        if filled_price is not None
        else float(order["breakeven_price"])
    )
    return {
        "id": f"order-{order['id']}",
        "opened_at": utc_now_text(),
        "status": "open",
        "order_id": order["id"],
        "strategy": order["strategy"],
        "contract_symbol": order["contract_symbol"],
        "ticker_symbol": order["ticker_symbol"],
        "expiration": order["expiration"],
        "strike": strike,
        "quantity": quantity,
        "premium_received": premium_received,
        "cash_required": strike * 100 * quantity,
        "breakeven_price": breakeven_price,
        "average_fill_price": filled_price,
        "filled_at": order.get("alpaca_filled_at"),
        "realized_pnl": 0,
    }


## Save a filled-order fallback position under an idempotent sort key.
## Repeated dashboard reconciliations overwrite the same record rather than creating duplicate positions.
def _save_filled_order_position(owner_partition, order):
    position = _create_open_position(order)
    put_item({
        "pk": owner_partition,
        "sk": f"POSITION#ORDER#{order['id']}",
        "item_type": "position",
        **position,
    })


## Decide whether a broker order represents an active filled CSP position.
## Accepted but unfilled limit orders are orders rather than positions and therefore do not consume a saved position slot.
def _should_track_open_position(order):
    return str(order.get("status", "")).lower() in FILLED_ORDER_STATUSES


## Record how one authenticated user responded to a saved recommendation.
## The owner-scoped run lookup prevents users from submitting decisions against another user's candidates.
def record_user_decision(
    user_id,
    run_id,
    contract_symbol,
    action,
    note="",
    alpaca_order=None,
    order_error=None,
    candidate_override=None,
):
    run = get_recommendation_run(user_id, run_id)
    if run is None:
        raise ValueError("Recommendation run not found.")

    candidate = find_candidate(run, contract_symbol)
    if candidate is None:
        raise ValueError("Candidate not found in recommendation run.")
    if candidate_override:
        if candidate_override.get("contractSymbol") != contract_symbol:
            raise ValueError("Candidate override does not match the selected contract.")
        candidate = candidate_override

    owner_partition = user_pk(user_id)
    client_order_id = (alpaca_order or {}).get("client_order_id")
    if action == "place_paper_order" and client_order_id:
        existing_lookup = get_item(
            f"{owner_partition}#ALPACA_CLIENT_ORDER#{client_order_id}",
            "ORDER",
        )
        if existing_lookup:
            decision_sk = existing_lookup.get("decision_sk")
            existing_decision = (
                get_item(owner_partition, decision_sk)
                if decision_sk
                else None
            )
            if existing_decision:
                return existing_decision

    decision = {
        "id": str(uuid4()),
        "created_at": utc_now_text(),
        "recommendation_run_id": run_id,
        "contract_symbol": contract_symbol,
        "ticker_symbol": candidate["tickerSymbol"],
        "action": action,
        "note": note,
        "agent_selected_contract": run["agent_review"].get("selected_contract"),
        "agent_decision": run["agent_review"].get("decision"),
        "alpaca_order_id": (alpaca_order or {}).get("id"),
        "order_error": order_error,
    }
    put_item({
        "pk": owner_partition,
        "sk": f"DECISION#{decision['created_at']}#{decision['id']}",
        "item_type": "user_decision",
        **decision,
    })

    if action != "place_paper_order":
        return decision

    order = _create_paper_order(decision, candidate, alpaca_order)
    order_sort_key = f"ORDER#{order['created_at']}#{order['id']}"
    put_item({
        "pk": owner_partition,
        "sk": order_sort_key,
        "item_type": "paper_order",
        **order,
    })
    if order.get("alpaca_order_id"):
        put_item({
            "pk": f"{owner_partition}#ALPACA_ORDER#{order['alpaca_order_id']}",
            "sk": "ORDER",
            "item_type": "order_lookup",
            "order_id": order["id"],
            "user_order_sk": order_sort_key,
        })
    if order.get("alpaca_client_order_id"):
        put_item({
            "pk": f"{owner_partition}#ALPACA_CLIENT_ORDER#{order['alpaca_client_order_id']}",
            "sk": "ORDER",
            "item_type": "client_order_lookup",
            "order_id": order["id"],
            "user_order_sk": order_sort_key,
            "decision_sk": f"DECISION#{decision['created_at']}#{decision['id']}",
        })
    if _should_track_open_position(order):
        _save_filled_order_position(owner_partition, order)
    return decision


## Update saved order records from the latest Alpaca statuses for one user.
## User-scoped lookup keys prevent identical broker order ids from crossing HELIOS account boundaries.
def reconcile_paper_orders(user_id, alpaca_orders):
    owner_partition = user_pk(user_id)
    updated_count = 0
    for alpaca_order in alpaca_orders:
        alpaca_order_id = alpaca_order.get("id")
        status = alpaca_order.get("status")
        if not alpaca_order_id or not status:
            continue

        lookup = get_item(
            f"{owner_partition}#ALPACA_ORDER#{alpaca_order_id}",
            "ORDER",
        )
        if not lookup:
            continue

        order_item = get_item(owner_partition, lookup["user_order_sk"])
        if not order_item:
            continue

        for field in ORDER_LIFECYCLE_FIELDS:
            value = alpaca_order.get(field)
            if value is not None:
                order_item[f"alpaca_{field}"] = value
        order_item["status"] = status
        _apply_fill_economics(order_item)
        put_item(order_item)
        if _should_track_open_position(order_item):
            _save_filled_order_position(owner_partition, order_item)
        updated_count += 1
    return updated_count


## Return one internal HELIOS paper-order record by its stable id.
## Trade-feedback routes use this owner-scoped lookup so a user can never annotate another account's order.
def get_paper_order_by_id(user_id, order_id, limit=500):
    for order in query_items(
        user_pk(user_id),
        "ORDER#",
        limit=limit,
        scan_forward=False,
    ):
        if order.get("id") == order_id:
            return order
    return None


## Import filled Alpaca CSP openings that predate HELIOS recommendation memory.
## Imported orders retain broker fill economics and source attribution, but leave recommendation fields empty so later prompts do not claim the agent suggested them.
def import_filled_csp_order_history(user_id, alpaca_orders):
    owner_partition = user_pk(user_id)
    existing_alpaca_order_ids = {
        order.get("alpaca_order_id")
        for order in query_items(
            owner_partition,
            "ORDER#",
            limit=1000,
            scan_forward=False,
        )
        if order.get("alpaca_order_id")
    }
    imported = []
    skipped_ambiguous = 0
    for alpaca_order in alpaca_orders or []:
        contract = parse_option_contract_symbol(alpaca_order.get("symbol"))
        is_filled_put_sale = (
            str(alpaca_order.get("status") or "").lower() == "filled"
            and str(alpaca_order.get("side") or "").lower() == "sell"
            and contract is not None
            and contract["option_type"] == "put"
        )
        if not is_filled_put_sale:
            continue

        # A filled put sale without an explicit sell_to_open intent could instead be
        # closing a long put, so it is counted and skipped rather than imported as a CSP.
        if str(alpaca_order.get("position_intent") or "").lower() != "sell_to_open":
            skipped_ambiguous += 1
            continue

        alpaca_order_id = alpaca_order.get("id")
        if not alpaca_order_id:
            continue
        lookup_pk = f"{owner_partition}#ALPACA_ORDER#{alpaca_order_id}"
        if alpaca_order_id in existing_alpaca_order_ids:
            continue

        filled_price = number_or_none(alpaca_order.get("filled_avg_price"))
        filled_quantity = number_or_none(alpaca_order.get("filled_qty"))
        if filled_price is None or not filled_quantity or filled_quantity <= 0:
            continue

        created_at = (
            alpaca_order.get("submitted_at")
            or alpaca_order.get("filled_at")
            or utc_now_text()
        )
        order_id = f"alpaca-{alpaca_order_id}"
        strike = float(contract["strike"])
        order = {
            "id": order_id,
            "created_at": created_at,
            "source": "alpaca_history_import",
            "status": "filled",
            "side": "sell",
            "strategy": "cash-secured put",
            "contract_symbol": alpaca_order["symbol"],
            "ticker_symbol": contract["ticker_symbol"],
            "expiration": contract["expiration"],
            "strike": strike,
            "quoted_premium": (
                (number_or_none(alpaca_order.get("limit_price")) or filled_price)
                * 100
                * filled_quantity
            ),
            "premium_received": filled_price * 100 * filled_quantity,
            "cash_required": strike * 100 * filled_quantity,
            "breakeven_price": strike - filled_price,
            "alpaca_order_id": alpaca_order_id,
            "alpaca_client_order_id": alpaca_order.get("client_order_id"),
            "alpaca_limit_price": alpaca_order.get("limit_price"),
            "alpaca_submitted_at": alpaca_order.get("submitted_at"),
            "alpaca_updated_at": alpaca_order.get("updated_at"),
            "alpaca_qty": alpaca_order.get("qty"),
            "alpaca_filled_qty": alpaca_order.get("filled_qty"),
            "alpaca_filled_avg_price": alpaca_order.get("filled_avg_price"),
            "alpaca_filled_at": alpaca_order.get("filled_at"),
            "entry_factors": {
                "availability": "not_recorded_before_helios_import",
            },
        }
        order_sort_key = f"ORDER#{created_at}#{order_id}"
        put_items([
            {
                "pk": owner_partition,
                "sk": order_sort_key,
                "item_type": "paper_order",
                **order,
            },
            {
                "pk": lookup_pk,
                "sk": "ORDER",
                "item_type": "order_lookup",
                "order_id": order_id,
                "user_order_sk": order_sort_key,
            },
        ])
        _save_filled_order_position(owner_partition, order)
        existing_alpaca_order_ids.add(alpaca_order_id)
        imported.append(order)

    return {
        "imported": len(imported),
        "orders": imported,
        "skipped_ambiguous_put_sales": skipped_ambiguous,
    }


## Close the DynamoDB fallback position created for one filled HELIOS order.
## Live Alpaca positions remain authoritative, but marking this fallback prevents a resolved contract from reappearing if the broker position endpoint is temporarily unavailable.
def close_fallback_order_position(
    user_id,
    order_id,
    resolution_type,
    closed_at,
    outcome_sort_key,
):
    owner_partition = user_pk(user_id)
    position_key = f"POSITION#ORDER#{order_id}"
    position = get_item(owner_partition, position_key)
    if not position:
        return False

    position.update({
        "status": "closed",
        "resolution_type": resolution_type,
        "closed_at": closed_at,
        "outcome_sk": outcome_sort_key,
    })
    put_item(position)
    return True
