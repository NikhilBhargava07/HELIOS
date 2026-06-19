"""Read portfolio summaries and recent history for the dashboard."""

from backend.memory.database import ensure_schema, get_connection
from backend.memory.serializers import (
    decision_from_row,
    order_from_row,
    position_from_row,
    recommendation_from_row,
)


def get_open_positions():
    """Return locally tracked positions still marked open."""
    ensure_schema()
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT * FROM positions WHERE status = 'open' ORDER BY opened_at ASC")
            return [position_from_row(row) for row in cursor.fetchall()]


def get_capital_summary(
    total_capital,
    max_csp_capital_percent,
    max_open_positions,
    open_positions=None,
):
    """Calculate local CSP collateral usage and position capacity."""
    positions = get_open_positions() if open_positions is None else open_positions
    committed_capital = sum(position["cash_required"] for position in positions)
    max_csp_capital = total_capital * max_csp_capital_percent
    return {
        "total_capital": total_capital,
        "max_csp_capital": max_csp_capital,
        "committed_capital": committed_capital,
        "available_csp_capital": max(0, max_csp_capital - committed_capital),
        "open_position_count": len(positions),
        "max_open_positions": max_open_positions,
        "open_positions": positions,
    }


def get_dashboard_data(total_capital, max_csp_capital_percent, max_open_positions):
    """Load local capital calculations and bounded recent history lists."""
    ensure_schema()
    open_positions = get_open_positions()
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT * FROM paper_orders ORDER BY created_at DESC LIMIT 20")
            paper_orders = [order_from_row(row) for row in cursor.fetchall()]
            cursor.execute("SELECT * FROM user_decisions ORDER BY created_at DESC LIMIT 20")
            decisions = [decision_from_row(row) for row in cursor.fetchall()]
            cursor.execute("SELECT * FROM recommendation_runs ORDER BY created_at DESC LIMIT 10")
            runs = [recommendation_from_row(row, []) for row in cursor.fetchall()]

    return {
        "capital": get_capital_summary(
            total_capital,
            max_csp_capital_percent,
            max_open_positions,
            open_positions=open_positions,
        ),
        "open_positions": open_positions,
        "paper_orders": list(reversed(paper_orders)),
        "user_decisions": list(reversed(decisions)),
        "recommendation_runs": list(reversed(runs)),
    }
