## DynamoDB-backed user decision and paper-order memory facade.

from backend.memory import dynamodb_store


## Delegate user decision recording to the active memory store.
## Recommendation routes call this wrapper after a user places or discards a paper trade.
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


## Delegate broker-order reconciliation to the active memory store.
## The dashboard service calls this before rendering order history.
def reconcile_paper_orders(alpaca_orders):
    return dynamodb_store.reconcile_paper_orders(alpaca_orders)
