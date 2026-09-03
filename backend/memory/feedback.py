## Store explicit user interpretation of paper-trade outcomes.
##
## Financial results and user satisfaction are intentionally separate. A CSP
## may lose option value while producing an assignment the user welcomed, so
## HELIOS records both dimensions rather than converting every trade into a
## simplistic win or loss label.

from backend.memory.dynamodb_store import put_item, query_items, user_pk, utc_now_text
from backend.memory.trades import get_paper_order_by_id


## Save or replace the authenticated user's feedback for one known paper order.
## The order lookup supplies trusted ticker and contract identifiers instead of accepting ownership-sensitive values from the browser.
def save_trade_feedback(
    user_id,
    opening_order_id,
    satisfaction,
    would_repeat,
    assignment_preference,
    reason_tags=None,
    note="",
):
    order = get_paper_order_by_id(user_id, opening_order_id)
    if not order:
        raise ValueError("Paper order not found.")

    now = utc_now_text()
    feedback = {
        "pk": user_pk(user_id),
        "sk": f"TRADE_FEEDBACK#{opening_order_id}",
        "item_type": "trade_feedback",
        "opening_order_id": opening_order_id,
        "recommendation_run_id": order.get("recommendation_run_id"),
        "ticker_symbol": order.get("ticker_symbol"),
        "contract_symbol": order.get("contract_symbol"),
        "satisfaction": satisfaction,
        "would_repeat": bool(would_repeat),
        "assignment_preference": assignment_preference,
        "reason_tags": list(dict.fromkeys(reason_tags or [])),
        "note": note.strip(),
        "updated_at": now,
    }
    put_item(feedback)
    return _public_feedback(feedback)


## Return recent explicit trade feedback newest first.
## DynamoDB keys are organized by order id for idempotent replacement, so chronological ordering is applied after the owner-scoped query.
def get_trade_feedback(user_id, limit=100):
    items = query_items(
        user_pk(user_id),
        "TRADE_FEEDBACK#",
        limit=limit,
        scan_forward=False,
    )
    return [
        _public_feedback(item)
        for item in sorted(
            items,
            key=lambda item: item.get("updated_at") or "",
            reverse=True,
        )
    ]


## Remove DynamoDB ownership keys before feedback is returned to routes or prompts.
## Broker credentials and unrelated profile data never enter these records.
def _public_feedback(item):
    return {
        key: item.get(key)
        for key in (
            "opening_order_id",
            "recommendation_run_id",
            "ticker_symbol",
            "contract_symbol",
            "satisfaction",
            "would_repeat",
            "assignment_preference",
            "reason_tags",
            "note",
            "updated_at",
        )
    }
