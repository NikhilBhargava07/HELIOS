## Run HELIOS's unattended scans three times a trading day and keep what they found.
##
## Nobody is watching when these run, so two guards decide whether a slot does any
## work. The broker's own clock says whether the market is actually open, which cron
## cannot know on a holiday or an early close. And a slot that already produced
## highlights today does nothing the second time, which makes a repeated delivery
## harmless and lets the schedule fire at both of a slot's possible UTC times so the
## local hour stays correct across daylight saving.

import json
import logging
from datetime import datetime, timedelta, timezone

from backend.api.services import (
    get_dashboard_with_cash_context,
    get_effective_available_csp_cash,
    get_safe_paper_account_summary,
)
from backend.broker.clients import create_option_data_client, create_stock_data_client
from backend.broker.trading import create_trading_client, get_paper_orders
from backend.memory.dynamodb_store import get_item, put_item, query_items, user_pk, utc_now_text
from backend.memory.holdings import build_holdings
from backend.memory.recommendations import save_recommendation_run
from backend.strategy.daily_triage import run_daily_triage
from backend.strategy.registry import STRATEGIES
from backend.users.profiles import get_user_broker_credentials, list_connected_broker_user_ids

logger = logging.getLogger(__name__)

HIGHLIGHT_SORT_KEY_PREFIX = "HIGHLIGHT"
SLOTS = ("open", "midday", "preclose")

# The exchange runs on New York time; the trading date is the one the market itself is having.
MARKET_TIMEZONE = timezone(timedelta(hours=-4))


## Return the trading date a scan belongs to, in the market's own timezone.
## Using UTC here would file an afternoon scan under the next day for part of the year.
def trading_date():
    return datetime.now(MARKET_TIMEZONE).date().isoformat()


## Build the sort key that makes one slot's highlights unique per day.
def highlight_sort_key(date, slot):
    return f"{HIGHLIGHT_SORT_KEY_PREFIX}#{date}#{slot}"


## Return today's highlights for one user, oldest slot first.
## The page reads this to show what HELIOS found before the user opened it.
def get_daily_highlights(user_id, date=None):
    return query_items(
        user_pk(user_id),
        f"{HIGHLIGHT_SORT_KEY_PREFIX}#{date or trading_date()}#",
        limit=len(SLOTS),
    )


## Return the most recent day's highlights, which is usually but not always today.
##
## Nothing has run yet before the opening scan, and nothing runs at all at a weekend or
## over a holiday. Showing an empty page then would suggest HELIOS had found nothing,
## when in fact it had not looked, so the last day it did look is shown and dated.
def get_latest_highlights(user_id):
    recent = query_items(
        user_pk(user_id),
        f"{HIGHLIGHT_SORT_KEY_PREFIX}#",
        limit=len(SLOTS) * 5,
        scan_forward=False,
    )
    if not recent:
        return [], None

    latest_date = recent[0].get("trading_date")
    same_day = [row for row in recent if row.get("trading_date") == latest_date]

    return sorted(same_day, key=lambda row: row.get("created_at") or ""), latest_date


## Collect what earlier slots already reported today, so a later scan can say what changed.
## Only the picks travel, because repeating a whole review back to the model would cost more than it adds.
def earlier_picks_today(user_id, date):
    return [
        {"slot": item.get("slot"), "picks": item.get("picks") or []}
        for item in get_daily_highlights(user_id, date)
        if item.get("picks")
    ]


## Ask the broker whether the market is actually trading right now.
## A calendar holiday or an early close looks exactly like a normal weekday to a cron expression.
def market_is_open(trading_client):
    clock = trading_client.get_clock()
    return bool(getattr(clock, "is_open", False))


## Assemble the account state every strategy scan needs for one user.
## Built once per slot and shared by all strategies, since it describes the account rather than any one trade.
def build_scan_inputs(user_id, trading_client, stock_data_client, option_data_client):
    alpaca_account = get_safe_paper_account_summary(trading_client=trading_client)
    broker_orders = get_paper_orders(limit=500, trading_client=trading_client)
    dashboard = get_dashboard_with_cash_context(
        user_id, alpaca_account, trading_client=trading_client, broker_orders=broker_orders,
    )
    capital = dashboard["capital"]

    return {
        "total_capital": capital["total_capital"],
        "current_open_positions": capital["open_position_count"],
        "committed_capital": capital["committed_capital"],
        "external_available_capital": get_effective_available_csp_cash(capital, alpaca_account),
        "portfolio_context": {
            "capital": capital,
            "open_csp_positions": dashboard["open_positions"],
            "holdings": build_holdings(user_id, dashboard.get("all_positions")),
        },
        "stock_data_client": stock_data_client,
        "option_data_client": option_data_client,
    }


## Save each strategy's offered candidates as an ordinary recommendation run.
##
## A pick is only useful if the user can act on it later, and acting goes through the
## same saved-run path a manual scan uses. Marking the run as automatic keeps the two
## apart in memory without giving them separate machinery.
def _save_offered_runs(user_id, offered, slot):
    run_ids = {}
    from backend.api.services import candidates_to_records

    for key, frame in offered.items():
        strategy = STRATEGIES[key]
        run = save_recommendation_run(
            user_id,
            candidates_to_records(frame),
            {"decision": "needs_review", "selected_contract": None,
             "summary": f"Automatic {slot} scan; see the day's highlights for the agent's picks.",
             "risk_note": "Quotes move, so a saved candidate is re-checked live before any order."},
            strategy_rules=strategy.strategy_rules,
            candidate_id_column=strategy.candidate_id_column,
        )
        run_ids[key] = run["id"]

    return run_ids


## Run one slot for one account, unless the market is shut or the slot already ran.
##
## The saved highlight is what the page shows later, and it records which run each pick
## came from so acting on one can re-check that exact candidate against a live quote.
def run_triage_slot(user_id, slot, force=False):
    date = trading_date()
    existing = get_item(user_pk(user_id), highlight_sort_key(date, slot))
    if existing and not force:
        return {"ok": True, "skipped": "slot_already_ran", "user_id": user_id, "slot": slot}

    credentials = get_user_broker_credentials(user_id)
    if not credentials or credentials.get("broker") != "alpaca":
        return {"ok": False, "error": "broker_not_connected", "user_id": user_id}

    api_key, secret_key = credentials["api_key"], credentials["secret_key"]
    trading_client = create_trading_client(api_key, secret_key)

    if not force and not market_is_open(trading_client):
        return {"ok": True, "skipped": "market_closed", "user_id": user_id, "slot": slot}

    stock_data_client = create_stock_data_client(api_key, secret_key)
    option_data_client = create_option_data_client(api_key, secret_key)
    scan_inputs = build_scan_inputs(user_id, trading_client, stock_data_client, option_data_client)

    triage = run_daily_triage(
        user_id,
        scan_inputs,
        stock_data_client,
        earlier_picks=earlier_picks_today(user_id, date),
    )
    offered = triage.pop("offered", {})
    run_ids = _save_offered_runs(user_id, offered, slot)

    # Each pick records the run holding its candidate, so acting on it later can find the exact row.
    picks = []
    for pick in triage.get("picks", []):
        picks.append({**pick, "recommendation_run_id": run_ids.get(pick.get("strategy_key"))})

    highlight = {
        "pk": user_pk(user_id),
        "sk": highlight_sort_key(date, slot),
        "item_type": "daily_highlight",
        "user_id": user_id,
        "slot": slot,
        "trading_date": date,
        "created_at": utc_now_text(),
        "market_read": triage.get("market_read", ""),
        "picks": picks,
        "passed_over": triage.get("passed_over", ""),
        "skipped_strategies": triage.get("skipped", {}),
        "candidate_counts": {key: len(frame) for key, frame in offered.items()},
        "recommendation_run_ids": run_ids,
        "review_source": triage.get("review_source"),
        "ai_error_code": triage.get("ai_error_code"),
    }
    put_item(highlight)
    logger.info("Triage %s for %s stored %s picks", slot, user_id[:8], len(picks))

    return {"ok": True, "user_id": user_id, "slot": slot, "picks": len(picks),
            "candidates": highlight["candidate_counts"]}


## Fan one slot out to every connected account, one asynchronous job each.
## A slow or unreachable broker for one user must not delay or block anybody else's scan.
def dispatch_scheduled_triage(slot):
    import os

    import boto3

    if slot not in SLOTS:
        raise ValueError(f"Unknown scan slot: {slot}")

    function_name = os.getenv("AWS_LAMBDA_FUNCTION_NAME")
    if not function_name:
        raise RuntimeError("AWS_LAMBDA_FUNCTION_NAME is required for scheduled scans.")

    lambda_client = boto3.client("lambda")
    user_ids = list_connected_broker_user_ids()
    failed = []

    for user_id in user_ids:
        try:
            lambda_client.invoke(
                FunctionName=function_name,
                InvocationType="Event",
                Payload=json.dumps({
                    "worker_action": "triage_slot",
                    "user_id": user_id,
                    "slot": slot,
                }).encode("utf-8"),
            )
        except Exception:
            logger.exception("Could not dispatch %s scan for user %s", slot, user_id)
            failed.append(user_id)

    return {"ok": not failed, "slot": slot,
            "users_dispatched": len(user_ids) - len(failed), "users_failed": len(failed)}
