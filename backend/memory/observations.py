## Store user-scoped option observations and trade outcomes.

from datetime import datetime, timezone
from uuid import uuid4

from backend.memory.dynamodb_store import (
    put_item,
    query_items,
    user_pk,
    utc_now_text,
)
from backend.memory.outcome_analysis import (
    build_outcome_snapshot,
    summarize_snapshot,
)


## Store one current-position snapshot, overwriting duplicate observations for the same contract and UTC day.
## Daily upserts preserve longitudinal evidence without letting repeated page refreshes inflate the apparent sample size.
def save_outcome_snapshot(user_id, position, context=None):
    observed_at = utc_now_text()
    observed_date = datetime.now(timezone.utc).date().isoformat()
    snapshot = build_outcome_snapshot(position)
    contract_symbol = (
        snapshot.get("contract_symbol")
        or position.get("symbol")
        or str(uuid4())
    )
    snapshot_id = f"{observed_date}:{contract_symbol}"
    item = {
        "pk": user_pk(user_id),
        "sk": f"OUTCOME_SNAPSHOT#{observed_date}#{contract_symbol}",
        "item_type": "outcome_snapshot",
        "id": snapshot_id,
        "observed_at": observed_at,
        "observed_date": observed_date,
        "ticker_symbol": snapshot.get("ticker_symbol"),
        "contract_symbol": snapshot.get("contract_symbol"),
        "snapshot": snapshot,
        "summary": summarize_snapshot(snapshot),
        "context": context or {},
    }
    put_item(item)
    return item


## Return recent outcome snapshots for one authenticated user.
## Newest observations appear first so prompts focus on the current state of open option risk.
def get_recent_outcome_snapshots(user_id, limit=20):
    return query_items(
        user_pk(user_id),
        "OUTCOME_SNAPSHOT#",
        limit=limit,
        scan_forward=False,
    )


## Recognize a sold option contract in either shape HELIOS stores positions in.
##
## A live Alpaca position states its signed quantity, where a negative number means
## the contract was sold. HELIOS' own fallback records omit that field, but they are
## only ever written for a sell-to-open order, so carrying a contract symbol is
## enough to identify one.
def is_short_option_position(position):
    signed_quantity = position.get("signed_quantity")
    if signed_quantity is not None:
        return signed_quantity < 0

    return bool(position.get("contract_symbol"))


## Capture daily observations for every current short option position.
## Shares and long contracts are reported as skipped rather than silently entering option learning memory,
## because only a sold contract carries the obligation these observations are watching.
def capture_current_option_outcome_snapshots(
    user_id,
    open_positions,
    context=None,
):
    captured = []
    skipped = []
    for position in open_positions or []:
        if not is_short_option_position(position):
            skipped.append({
                "symbol": (
                    position.get("symbol")
                    or position.get("contract_symbol")
                ),
                "reason": "not_a_short_option",
            })
            continue
        captured.append(
            save_outcome_snapshot(
                user_id,
                position,
                context=context,
            )
        )
    return {
        "captured": len(captured),
        "skipped": skipped,
        "snapshots": captured,
        "backend": "dynamodb",
    }
