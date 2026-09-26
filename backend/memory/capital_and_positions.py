## Build user-scoped capital, position, and paper-order memory views.

from backend.capital import strategy_capacity
from backend.memory.dynamodb_store import query_items, user_pk


## Return open CSP fallback positions saved for one authenticated user.
## Live Alpaca positions override these records whenever the broker API is available.
def get_open_positions(user_id):
    return [
        item
        for item in query_items(user_pk(user_id), "POSITION#")
        if item.get("status") == "open"
    ]


## Return recent paper-order history newest first.
## Newest-first ordering matches the dashboard's "Recent Paper Orders" label and avoids reversing DynamoDB results.
def get_saved_paper_orders(user_id, limit=20):
    return query_items(
        user_pk(user_id),
        "ORDER#",
        limit=limit,
        scan_forward=False,
    )


## Calculate CSP capital usage from the supplied or saved open positions.
## Strategy allocation and position-count limits stay deterministic even when Alpaca is temporarily unavailable.
def get_capital_summary(
    user_id,
    total_capital,
    max_csp_capital_percent,
    max_open_positions,
    open_positions=None,
):
    positions = (
        get_open_positions(user_id)
        if open_positions is None
        else open_positions
    )
    committed_capital = sum(
        position["cash_required"]
        for position in positions
    )
    max_csp_capital, available_csp_capital = strategy_capacity(
        total_capital,
        max_csp_capital_percent,
        committed_capital,
    )
    return {
        "total_capital": total_capital,
        "max_csp_capital": max_csp_capital,
        "committed_capital": committed_capital,
        "available_csp_capital": available_csp_capital,
        "open_position_count": len(positions),
        "max_open_positions": max_open_positions,
        "open_positions": positions,
    }


## Build the memory-only dashboard payload for one user.
## The API service enriches this fallback data with live Alpaca account and position information.
def get_dashboard_data(
    user_id,
    total_capital,
    max_csp_capital_percent,
    max_open_positions,
):
    open_positions = get_open_positions(user_id)
    return {
        "capital": get_capital_summary(
            user_id,
            total_capital,
            max_csp_capital_percent,
            max_open_positions,
            open_positions,
        ),
        "open_positions": open_positions,
        "paper_orders": get_saved_paper_orders(user_id),
    }
