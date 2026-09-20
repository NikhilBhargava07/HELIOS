## Finalize short option-leg outcomes from explicit Alpaca lifecycle evidence.
##
## A position disappearing from Alpaca is not enough to label a trade assigned,
## expired, or closed. This module requires a filled buy-to-close order or an
## option lifecycle activity, then stores neutral economic measurements rather
## than a simplistic success/failure label.
##
## Puts and calls end differently. An assigned put buys shares, so the option is
## final but the shares' result is not. A call sold against shares already held
## delivers them when exercised, which settles that earlier share result instead
## of opening a new one and completes a wheel cycle.

from datetime import datetime, timezone

from backend.broker.trading import parse_option_contract_symbol
from backend.config import SHARES_PER_CONTRACT
from backend.memory.dynamodb_store import (
    get_item,
    put_item,
    query_items,
    user_pk,
    utc_now_text,
)
from backend.memory.observations import get_recent_outcome_snapshots
from backend.memory.outcome_analysis import number_or_none
from backend.memory.trades import close_fallback_order_position


## Parse an ISO timestamp for chronological order matching.
## Invalid or missing broker timestamps sort before valid timestamps instead of crashing the scheduled observation job.
def _timestamp(value):
    if not value:
        return datetime.min.replace(tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return datetime.min.replace(tzinfo=timezone.utc)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


## Build a stable outcome key from the original HELIOS order.
## Repeated scheduled observations overwrite the same lifecycle record instead of manufacturing duplicate completed trades.
def _outcome_sort_key(order):
    opened_at = order.get("alpaca_filled_at") or order.get("created_at") or "unknown"
    return f"OUTCOME#{opened_at}#{order['id']}"


## Return the most recent saved observation for one option contract.
## This preserves the final known price, P&L, and assignment-pressure context beside the terminal broker event.
def _latest_snapshot_by_contract(user_id):
    latest = {}
    for item in get_recent_outcome_snapshots(user_id, limit=200):
        contract = item.get("contract_symbol") or item.get("snapshot", {}).get("contract_symbol")
        if contract and contract not in latest:
            latest[contract] = item
    return latest


## Identify filled buy orders that factually closed a short option after its opening fill.
## Matching requires the exact contract, a filled quantity and price, and a timestamp after the sell-to-open order.
def _matching_closing_orders(opening_order, broker_orders):
    contract = opening_order.get("contract_symbol")
    opened_at = _timestamp(opening_order.get("alpaca_filled_at") or opening_order.get("created_at"))
    matches = []
    for order in broker_orders or []:
        side = str(order.get("side") or "").lower()
        status = str(order.get("status") or "").lower()
        position_intent = str(order.get("position_intent") or "").lower()
        filled_at = _timestamp(order.get("filled_at"))
        filled_qty = number_or_none(order.get("filled_qty"))
        filled_price = number_or_none(order.get("filled_avg_price"))
        if (
            order.get("symbol") == contract
            and side == "buy"
            and status == "filled"
            and position_intent in {"", "buy_to_close"}
            and filled_qty
            and filled_qty > 0
            and filled_price is not None
            and filled_at > opened_at
        ):
            matches.append(order)
    return sorted(matches, key=lambda item: _timestamp(item.get("filled_at")))


## Match assignment, expiration, or cash-settlement activity to one exact option symbol.
## Assignment takes precedence because it is the event that moves shares, either buying them under a put or delivering them under a call.
def _matching_lifecycle_activity(opening_order, activities):
    contract_symbol = opening_order.get("contract_symbol")
    opened_at = _timestamp(
        opening_order.get("alpaca_filled_at")
        or opening_order.get("created_at")
    )
    matching = [
        activity
        for activity in activities or []
        if activity.get("symbol") == contract_symbol
        and _timestamp(
            activity.get("transaction_time")
            or activity.get("date")
        ) > opened_at
    ]
    priority = {"OPASN": 0, "OPEXP": 1, "OPCSH": 2}
    return min(
        matching,
        key=lambda item: priority.get(str(item.get("activity_type") or "").upper(), 99),
        default=None,
    )


## Resolve one no-longer-open short option from a closing order or lifecycle activity.
## The result reports measurable option economics while keeping assignment distinct from a realized stock gain or loss.
def _resolve_outcome(opening_order, broker_orders, activities):
    opening_quantity = number_or_none(opening_order.get("alpaca_filled_qty")) or 1
    closing_orders = _matching_closing_orders(opening_order, broker_orders)
    closing_quantity = sum(number_or_none(order.get("filled_qty")) or 0 for order in closing_orders)
    if closing_quantity >= opening_quantity:
        closing_debit = sum(
            (number_or_none(order.get("filled_avg_price")) or 0)
            * SHARES_PER_CONTRACT
            * (number_or_none(order.get("filled_qty")) or 0)
            for order in closing_orders
        )
        return {
            "resolution_type": "bought_to_close",
            "assigned": False,
            "closing_debit": closing_debit,
            "closed_at": max(
                closing_orders,
                key=lambda order: _timestamp(order.get("filled_at")),
            ).get("filled_at"),
            "evidence": {
                "closing_order_ids": [order.get("id") for order in closing_orders],
            },
        }

    activity = _matching_lifecycle_activity(opening_order, activities)
    if not activity:
        return None

    activity_type = str(activity.get("activity_type") or "").upper()
    resolution_type = {
        "OPASN": "assigned",
        "OPEXP": "expired",
        "OPCSH": "cash_settled",
    }.get(activity_type)
    if not resolution_type:
        return None
    return {
        "resolution_type": resolution_type,
        "assigned": activity_type == "OPASN",
        "closing_debit": 0.0,
        "closed_at": (
            activity.get("transaction_time")
            or activity.get("date")
            or utc_now_text()
        ),
        "evidence": {
            "activity_id": activity.get("id"),
            "activity_type": activity_type,
        },
    }


## Build the persistent nonbinary outcome record for one resolved option leg.
##
## An assigned put retains the premium but leaves the acquired shares' eventual
## result explicitly unresolved. An exercised covered call is the mirror image:
## the shares are delivered at the strike, so it creates no cash obligation and
## its share result is final, measured against what those shares really cost.
def _build_completed_outcome(order, contract, resolution, latest_snapshot):
    opening_credit = number_or_none(order.get("premium_received"))
    closing_debit = number_or_none(resolution.get("closing_debit"))
    option_realized_pnl = (
        opening_credit - closing_debit
        if opening_credit is not None and closing_debit is not None
        else None
    )
    premium_retained_percent = (
        option_realized_pnl / opening_credit * 100
        if opening_credit and option_realized_pnl is not None
        else None
    )
    assigned = resolution["assigned"]
    quantity = number_or_none(order.get("alpaca_filled_qty")) or 1
    strike = number_or_none(order.get("strike"))
    secured_by_shares = contract["option_type"] == "call"
    called_away = assigned and secured_by_shares
    shares = quantity * SHARES_PER_CONTRACT
    share_cost = number_or_none(order.get("cost_basis"))
    return {
        "item_type": "completed_outcome",
        "status": "complete",
        "completed_at": resolution["closed_at"],
        "opening_order_id": order["id"],
        "opening_source": order.get("source", "helios_recommendation"),
        "alpaca_opening_order_id": order.get("alpaca_order_id"),
        "recommendation_run_id": order.get("recommendation_run_id"),
        "contract_symbol": order.get("contract_symbol"),
        "ticker_symbol": order.get("ticker_symbol"),
        "option_type": contract["option_type"],
        "resolution_type": resolution["resolution_type"],
        "assigned": assigned,
        "quantity": quantity,
        "strike": strike,
        "expiration": order.get("expiration"),
        "opening_credit": opening_credit,
        "closing_debit": closing_debit,
        "option_realized_pnl": option_realized_pnl,
        "premium_retained_percent": premium_retained_percent,
        "assignment_cash_obligation": (
            strike * shares if assigned and strike and not secured_by_shares else None
        ),
        "effective_share_cost": (
            number_or_none(order.get("breakeven_price"))
            if assigned and not secured_by_shares
            else None
        ),
        "shares_called_away": shares if called_away else None,
        "share_sale_proceeds": strike * shares if called_away and strike else None,
        "share_realized_pnl": (
            (strike - share_cost) * shares
            if called_away and strike is not None and share_cost is not None
            else None
        ),
        "underlying_outcome_pending": assigned and not secured_by_shares,
        "entry_factors": order.get("entry_factors") or {},
        "latest_open_snapshot": (latest_snapshot or {}).get("snapshot"),
        "latest_open_context": (latest_snapshot or {}).get("context"),
        "evidence": resolution["evidence"],
        "interpretation": _interpretation(assigned, secured_by_shares),
    }


## State plainly what a resolved leg does and does not settle.
## The wording is stored beside the numbers so later prompts cannot read a retained premium as a finished profit.
def _interpretation(assigned, secured_by_shares):
    if assigned and secured_by_shares:
        return (
            "The covered call was exercised and the shares were delivered at the strike, "
            "so both the premium and the shares' gain or loss against their real cost are final."
        )
    if assigned:
        return (
            "The cash-secured put ended in assignment; premium was retained, "
            "but the acquired shares' later gain or loss is not yet final."
        )
    if secured_by_shares:
        return "The covered call is closed, the shares were kept, and its premium retention is measurable."
    return "The cash-secured put option leg is closed and its premium retention is measurable."


## Settle the share side of earlier assignments when a covered call delivers those shares.
##
## An assigned put leaves shares whose eventual result is unknown, and being
## called away is the event that answers it. Alpaca does not say which lot was
## delivered, so the oldest pending assignment is settled first, the way shares
## are conventionally accounted for. Settling stops at the first assignment the
## called-away shares do not fully cover, because a partial match would have to
## be guessed at, and a pending record is more honest than an invented one.
def _settle_called_away_assignments(user_id, outcome):
    shares_available = outcome.get("shares_called_away") or 0
    sale_price = number_or_none(outcome.get("strike"))
    if not shares_available or sale_price is None:
        return []

    owner_partition = user_pk(user_id)
    pending_assignments = sorted(
        (
            item
            for item in query_items(owner_partition, "OUTCOME#", limit=200, scan_forward=False)
            if item.get("status") == "complete"
            and item.get("assigned")
            and item.get("underlying_outcome_pending")
            and item.get("ticker_symbol") == outcome.get("ticker_symbol")
        ),
        key=lambda item: _timestamp(item.get("completed_at")),
    )

    settled = []
    for assignment in pending_assignments:
        shares = (number_or_none(assignment.get("quantity")) or 0) * SHARES_PER_CONTRACT
        share_cost = number_or_none(assignment.get("effective_share_cost"))
        if not shares or share_cost is None or shares > shares_available:
            break

        shares_available -= shares
        assignment.update({
            "underlying_outcome_pending": False,
            "underlying_resolution": "called_away",
            "underlying_resolved_at": outcome["completed_at"],
            "underlying_realized_pnl": (sale_price - share_cost) * shares,
            "underlying_evidence": {
                "covered_call_contract_symbol": outcome.get("contract_symbol"),
                "covered_call_opening_order_id": outcome.get("opening_order_id"),
            },
            "interpretation": (
                "The assigned shares were later called away by a covered call, so this wheel cycle is "
                "complete and both the premium and the shares' gain or loss are final."
            ),
        })
        put_item(assignment)
        settled.append(assignment)

    return settled


## Finalize every saved filled short option whose position is no longer open.
## Ambiguous disappearances are returned for review and remain uncompleted until Alpaca supplies factual close, assignment, or expiration evidence.
def finalize_trade_outcomes(
    user_id,
    live_positions,
    broker_orders,
    option_activities,
):
    owner_partition = user_pk(user_id)
    # Any contract still open at the broker, whatever strategy sold it, is not yet resolved.
    open_contracts = {
        position.get("contract_symbol")
        for position in live_positions or []
        if position.get("contract_symbol")
    }
    latest_snapshots = _latest_snapshot_by_contract(user_id)
    saved_orders = query_items(
        owner_partition,
        "ORDER#",
        limit=200,
        scan_forward=False,
    )
    completed = []
    unresolved = []
    settled_assignments = []
    for order in saved_orders:
        # The contract symbol, not the stored label, decides how a leg is settled.
        contract = parse_option_contract_symbol(order.get("contract_symbol"))
        if contract is None or str(order.get("status") or "").lower() != "filled":
            continue
        if order["contract_symbol"] in open_contracts:
            continue

        outcome_sk = _outcome_sort_key(order)
        existing = get_item(owner_partition, outcome_sk)
        if existing and existing.get("status") == "complete":
            continue
        resolution = _resolve_outcome(order, broker_orders, option_activities)
        if not resolution:
            unresolved.append({
                "contract_symbol": order["contract_symbol"],
                "opening_order_id": order["id"],
                "reason": "awaiting_broker_lifecycle_evidence",
            })
            continue

        outcome = {
            "pk": owner_partition,
            "sk": outcome_sk,
            **_build_completed_outcome(
                order,
                contract,
                resolution,
                latest_snapshots.get(order["contract_symbol"]),
            ),
        }
        put_item(outcome)
        close_fallback_order_position(
            user_id,
            order["id"],
            outcome["resolution_type"],
            outcome["completed_at"],
            outcome_sk,
        )
        completed.append(outcome)
        settled_assignments.extend(_settle_called_away_assignments(user_id, outcome))

    return {
        "completed": len(completed),
        "outcomes": completed,
        "unresolved": unresolved,
        "assignments_settled": len(settled_assignments),
    }


## Return completed option outcomes newest opening first for profile and prompt memory.
## Assignment outcomes remain included but carry underlying_outcome_pending until the shares are sold, so they cannot be mistaken for completed stock profits.
def get_completed_trade_outcomes(user_id, limit=100):
    return [
        item
        for item in query_items(
            user_pk(user_id),
            "OUTCOME#",
            limit=limit,
            scan_forward=False,
        )
        if item.get("status") == "complete"
    ]
