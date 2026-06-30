## DynamoDB-backed user decision and paper-order memory facade.

from backend.memory import dynamodb_store


## Record a discard, failed order, or successful order submission.
def record_user_decision(
    run_id,
    contract_symbol,
    action,
    note="",
    alpaca_order=None,
    order_error=None,
):
    return dynamodb_store.record_user_decision(
        run_id,
        contract_symbol,
        action,
        note=note,
        alpaca_order=alpaca_order,
        order_error=order_error,
    )


## Update saved order statuses and broker details from Alpaca snapshots.
def reconcile_paper_orders(alpaca_orders):
    return dynamodb_store.reconcile_paper_orders(alpaca_orders)
