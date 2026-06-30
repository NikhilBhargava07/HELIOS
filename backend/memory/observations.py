## DynamoDB-backed candidate observation and trade outcome memory facade.

from backend.memory import dynamodb_store


## Capture due candidate checkpoints when scheduled observation support exists.
def capture_due_candidate_observations(limit=200):
    return dynamodb_store.capture_due_candidate_observations(limit=limit)


## Record a realized trade result for future learning.
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
