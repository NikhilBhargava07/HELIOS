## Store user-scoped CSP observations and trade outcomes.

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
## Newest observations appear first so prompts focus on the current state of active CSP risk.
def get_recent_outcome_snapshots(user_id, limit=20):
    return query_items(
        user_pk(user_id),
        "OUTCOME_SNAPSHOT#",
        limit=limit,
        scan_forward=False,
    )


## Capture daily observations for all current short-put positions.
## Non-CSP positions are reported as skipped rather than silently entering CSP learning memory.
def capture_current_csp_outcome_snapshots(
    user_id,
    open_positions,
    context=None,
):
    captured = []
    skipped = []
    for position in open_positions or []:
        if position.get("strategy") != "cash-secured put":
            skipped.append({
                "symbol": (
                    position.get("symbol")
                    or position.get("contract_symbol")
                ),
                "reason": "not_cash_secured_put",
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
