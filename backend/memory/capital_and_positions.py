## DynamoDB-backed capital and positions memory facade.

from backend.memory import dynamodb_store


## Delegate open-position lookup to the active memory store.
## This wrapper preserves a stable import path for dashboard code.
def get_open_positions():
    return dynamodb_store.get_open_positions()


## Delegate capital-summary calculation to the active memory store.
## Strategy rules stay centralized even if the storage engine changes again.
def get_capital_summary(
    total_capital,
    max_csp_capital_percent,
    max_open_positions,
    open_positions=None,
):
    return dynamodb_store.get_capital_summary(
        total_capital,
        max_csp_capital_percent,
        max_open_positions,
        open_positions=open_positions,
    )


## Delegate memory-only dashboard construction to the active memory store.
## The API service enriches this base payload with live Alpaca data.
def get_dashboard_data(total_capital, max_csp_capital_percent, max_open_positions):
    return dynamodb_store.get_dashboard_data(
        total_capital,
        max_csp_capital_percent,
        max_open_positions,
    )
