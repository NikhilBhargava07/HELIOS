## DynamoDB-backed capital and positions memory facade.

from backend.memory import dynamodb_store


## Return locally tracked positions still marked open.
def get_open_positions():
    return dynamodb_store.get_open_positions()


## Calculate local CSP collateral usage and position capacity.
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


## Load local capital calculations and bounded recent history lists.
def get_dashboard_data(total_capital, max_csp_capital_percent, max_open_positions):
    return dynamodb_store.get_dashboard_data(
        total_capital,
        max_csp_capital_percent,
        max_open_positions,
    )
