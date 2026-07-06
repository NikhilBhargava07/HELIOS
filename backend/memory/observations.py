## DynamoDB-backed candidate observation and trade outcome memory facade.

from backend.memory import dynamodb_store


## Delegate scheduled candidate observation capture to the active memory store.
## This keeps future EventBridge jobs decoupled from the database implementation.
def capture_due_candidate_observations(limit=200):
    return dynamodb_store.capture_due_candidate_observations(limit=limit)


## Capture current open-CSP outcome snapshots from live broker positions.
## These records let HELIOS learn from active drawdowns or profitable trades before final expiration.
def capture_current_csp_outcome_snapshots(open_positions, context=None):
    return dynamodb_store.capture_current_csp_outcome_snapshots(
        open_positions,
        context=context,
    )


## Return recent open-position outcome snapshots for debugging and agent memory.
## The API uses this to verify HELIOS is retaining nuanced lessons from current CSPs.
def get_recent_outcome_snapshots(limit=20):
    return dynamodb_store.get_recent_outcome_snapshots(limit=limit)


## Delegate manual trade-outcome recording to the active memory store.
## The memory API calls this when the user supplies or confirms a trade result.
def record_trade_outcome(
    decision_id,
    status,
    outcome_label,
    closing_cost=None,
    realized_pnl=None,
    assigned=None,
    expired_worthless=None,
    notes="",
    raw_outcome=None,
):
    return dynamodb_store.record_trade_outcome(
        decision_id,
        status,
        outcome_label,
        closing_cost=closing_cost,
        realized_pnl=realized_pnl,
        assigned=assigned,
        expired_worthless=expired_worthless,
        notes=notes,
        raw_outcome=raw_outcome,
    )
