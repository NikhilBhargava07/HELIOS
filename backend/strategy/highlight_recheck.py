## Re-check one saved pick against live prices before the user acts on it.
##
## A pick found at the open is hours old by the time it is read, and HELIOS refuses to
## place an order from a stale scan. Rather than widen that rule, acting on a pick
## re-scans the single ticker behind it and saves the result as a fresh run, so the
## order then travels the ordinary path with every safety check intact.
##
## The answer is deliberately not a yes or no. A contract can fail for reasons worth
## reading, and another strike on the same ticker is often still worth taking, so the
## re-check reports what the ticker offers now rather than only whether one row survived.

import logging

from backend.api.services import candidates_to_records
from backend.memory.recommendations import save_recommendation_run
from backend.strategy.recommender import available_strategy_capital
from backend.strategy.registry import get_strategy
from backend.strategy.spec import ScanContext

logger = logging.getLogger(__name__)


## Re-scan the one ticker behind a pick and report what it offers right now.
##
## Returns the pick itself when it still qualifies, the other candidates on that
## ticker when it does not, and a fresh run id whenever anything qualified, because
## placing needs a scan the freshness rule will accept.
def recheck_pick(user_id, strategy_key, identifier, ticker_symbol, scan_inputs):
    strategy = get_strategy(strategy_key)
    available_capital = available_strategy_capital(
        strategy,
        scan_inputs["total_capital"],
        scan_inputs["committed_capital"],
        scan_inputs["external_available_capital"],
    )
    portfolio_context = scan_inputs.get("portfolio_context") or {}

    # The exposure and eligibility rules can change during the day: shares may have been
    # sold, or a put opened on this very ticker since the pick was made.
    if ticker_symbol not in strategy.eligible_tickers(portfolio_context):
        return {
            "qualifies": False,
            "reason": (
                f"{ticker_symbol} no longer qualifies for a {strategy.short_label}, because "
                f"it requires {strategy.eligibility_requirement}."
            ),
            "candidate": None,
            "alternatives": [],
            "recommendation_run_id": None,
        }

    from backend.market.trends import get_latest_stock_prices

    try:
        latest_prices = get_latest_stock_prices([ticker_symbol], stock_data_client=scan_inputs["stock_data_client"])
    except Exception as error:
        logger.warning("Price lookup failed during re-check of %s: %s", ticker_symbol, type(error).__name__)
        latest_prices = {}

    scan = strategy.find_candidates(
        strategy,
        [ticker_symbol],
        ScanContext(
            available_capital=available_capital,
            latest_prices=latest_prices,
            portfolio_context=portfolio_context,
            stock_data_client=scan_inputs["stock_data_client"],
            option_data_client=scan_inputs["option_data_client"],
        ),
    )
    if scan.candidates.empty:
        return {
            "qualifies": False,
            "reason": f"Nothing on {ticker_symbol} passes the {strategy.short_label} rules right now.",
            "candidate": None,
            "alternatives": [],
            "recommendation_run_id": None,
        }

    records = candidates_to_records(scan.candidates)
    match = next(
        (record for record in records if record.get(strategy.candidate_id_column) == identifier),
        None,
    )

    # Saved as a run so placing it travels the same path a manual scan's candidate does.
    run = save_recommendation_run(
        user_id,
        records,
        {
            "decision": "needs_review" if match else "reject_all",
            "selected_contract": identifier if match else None,
            "summary": (
                f"Re-checked {identifier} against live prices."
                if match
                else f"{identifier} no longer qualifies; these are {ticker_symbol}'s current candidates."
            ),
            "risk_note": "Re-checked on demand, so these numbers are current rather than from the earlier scan.",
        },
        strategy_rules=strategy.strategy_rules,
        candidate_id_column=strategy.candidate_id_column,
    )

    return {
        "qualifies": match is not None,
        "reason": (
            "Still qualifies at current prices."
            if match
            else f"{identifier} is no longer among {ticker_symbol}'s best candidates, but these are."
        ),
        "candidate": match,
        "alternatives": [record for record in records if record is not match],
        "recommendation_run_id": run["id"],
        "strategy_key": strategy.key,
    }
