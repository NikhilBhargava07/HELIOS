## Summarize the shares a user holds, what they really cost, and how many are free to cover.
##
## A covered call is secured by 100 shares, so it needs three facts per ticker:
## how many shares are held, how many are already committed to an open short
## call, and what those shares actually cost. That last number is the real cost
## basis, which subtracts the premium collected on any put that was assigned to
## deliver the shares. The broker's average entry price ignores that premium, so
## it overstates the cost and would block calls that are profitable overall.

from backend.memory.outcomes import get_completed_trade_outcomes

SHARES_PER_CONTRACT = 100


## Total the put premium already collected on assignments whose shares are still held, by ticker.
## Only pending assignments count: once the shares are sold, that premium no longer belongs to the shares on hand.
def _premium_from_pending_assignments(user_id):
    premiums = {}
    for outcome in get_completed_trade_outcomes(user_id, limit=200):
        ticker = outcome.get("ticker_symbol")
        if ticker and outcome.get("assigned") and outcome.get("underlying_outcome_pending"):
            premiums[ticker] = premiums.get(ticker, 0) + (outcome.get("opening_credit") or 0)

    return premiums


## Build one holding record per ticker with at least one long share.
## Stock is counted long-only, since short shares cannot secure a covered call, and covered shares are capped at shares held.
def build_holdings(user_id, positions):
    shares = {}
    entry_cost = {}
    covered = {}

    for position in positions or []:
        ticker = position.get("ticker_symbol")
        if not ticker:
            continue

        quantity = position.get("quantity") or 0
        if position.get("strategy") == "stock" and quantity > 0:
            shares[ticker] = shares.get(ticker, 0) + quantity
            entry_cost[ticker] = entry_cost.get(ticker, 0) + quantity * (position.get("average_entry_price") or 0)
        elif position.get("option_type") == "call" and (position.get("signed_quantity") or 0) < 0:
            covered[ticker] = covered.get(ticker, 0) + abs(position["signed_quantity"]) * SHARES_PER_CONTRACT

    if not shares:
        return {}

    premiums = _premium_from_pending_assignments(user_id)
    holdings = {}
    for ticker, quantity in shares.items():
        covered_shares = min(covered.get(ticker, 0), quantity)
        holdings[ticker] = {
            "shares": quantity,
            "broker_cost_basis": entry_cost[ticker] / quantity,
            "cost_basis": (entry_cost[ticker] - premiums.get(ticker, 0)) / quantity,
            "covered_shares": covered_shares,
            "uncovered_shares": quantity - covered_shares,
        }

    return holdings
