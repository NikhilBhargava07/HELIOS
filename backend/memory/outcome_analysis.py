## Build nuanced CSP outcome snapshots from live broker positions.
##
## This module avoids simple win/loss labels. A cash-secured put can be
## financially painful while still being strategically acceptable if the user
## wanted assignment. These helpers separate money impact, assignment risk,
## timing quality, and future lesson categories so HELIOS can learn with more
## human-like nuance.

from datetime import datetime, timezone


## Safely coerce incoming broker or memory values into floats.
## Alpaca values may already be numbers or may arrive as strings, so every
## outcome calculation goes through this helper before doing math.
def number_or_none(value):
    if value is None:
        return None

    try:
        return float(value)
    except (TypeError, ValueError):
        return None


## Calculate a percentage while protecting against missing or zero denominators.
## Outcome snapshots use this for P/L versus premium and P/L versus reserved cash.
def percent_of(value, denominator):
    value = number_or_none(value)
    denominator = number_or_none(denominator)

    if value is None or not denominator:
        return None

    return (value / denominator) * 100


## Estimate how many calendar days remain before the option expires.
## This is intentionally calendar-based because it is used for broad learning
## context, not precise trading-session timing.
def days_to_expiration(expiration):
    if not expiration:
        return None

    try:
        expiration_date = datetime.fromisoformat(expiration).date()
    except ValueError:
        return None

    return (expiration_date - datetime.now(timezone.utc).date()).days


## Classify the money side of an open CSP without judging whether the trade was
## good or bad. Large losses relative to received premium are treated as more
## severe because they show the option moved meaningfully against the seller.
def classify_financial_status(position):
    unrealized_pnl = number_or_none(position.get("unrealized_pnl"))
    premium_received = number_or_none(position.get("premium_received"))
    cash_required = number_or_none(position.get("cash_required"))

    if unrealized_pnl is None:
        return "unknown"
    if unrealized_pnl > 0:
        return "profitable"
    if unrealized_pnl == 0:
        return "neutral"

    loss_vs_premium = abs(percent_of(unrealized_pnl, premium_received) or 0)
    loss_vs_cash = abs(percent_of(unrealized_pnl, cash_required) or 0)

    if loss_vs_premium >= 200 or loss_vs_cash >= 10:
        return "deeply_losing"
    if loss_vs_premium >= 75 or loss_vs_cash >= 3:
        return "losing"

    return "slightly_losing"


## Estimate assignment pressure from option-specific fields available in the
## broker position. Underlying stock price will make this stronger later, but
## current option value, P/L, and days left already provide useful signals.
def classify_assignment_status(position):
    financial_status = classify_financial_status(position)
    dte = days_to_expiration(position.get("expiration"))
    market_value = number_or_none(position.get("market_value"))
    premium_received = number_or_none(position.get("premium_received"))

    if financial_status == "deeply_losing":
        return "elevated"
    if financial_status == "losing" and dte is not None and dte <= 14:
        return "elevated"
    if financial_status in {"losing", "slightly_losing"}:
        return "possible"
    if market_value is not None and premium_received and abs(market_value) > premium_received:
        return "possible"

    return "unlikely"


## Decide whether the entry timing looks clean, stressed, or too early based on
## current P/L and time remaining. This is not a final judgment; it is a compact
## label that future prompts can use as context.
def classify_timing_quality(position):
    financial_status = classify_financial_status(position)
    dte = days_to_expiration(position.get("expiration"))

    if financial_status == "profitable":
        return "working_so_far"
    if financial_status == "deeply_losing":
        return "stressed_entry"
    if financial_status in {"losing", "slightly_losing"} and dte is not None and dte > 21:
        return "early_or_volatile"
    if financial_status in {"losing", "slightly_losing"}:
        return "needs_monitoring"

    return "unclear"


## Identify the kind of lesson HELIOS should consider saving from this position.
## This gives the memory system a non-binary way to remember whether the main
## issue was timing, assignment risk, sizing, or simply unknown.
def classify_lesson_type(position):
    financial_status = classify_financial_status(position)
    cash_required = number_or_none(position.get("cash_required")) or 0

    if cash_required >= 25000 and financial_status in {"losing", "deeply_losing"}:
        return "sizing_and_assignment_risk"
    if financial_status == "deeply_losing":
        return "premium_or_timing_trap"
    if financial_status in {"losing", "slightly_losing"}:
        return "monitor_assignment_risk"
    if financial_status == "profitable":
        return "candidate_working_so_far"

    return "insufficient_data"


## Build a durable outcome snapshot from one normalized CSP position.
## The returned record is designed for DynamoDB storage and future LLM prompt
## context, while still being readable enough for debugging from the memory API.
def build_outcome_snapshot(position):
    premium_received = number_or_none(position.get("premium_received"))
    cash_required = number_or_none(position.get("cash_required"))
    unrealized_pnl = number_or_none(position.get("unrealized_pnl"))

    return {
        "ticker_symbol": position.get("ticker_symbol"),
        "contract_symbol": position.get("contract_symbol"),
        "expiration": position.get("expiration"),
        "strike": number_or_none(position.get("strike")),
        "quantity": number_or_none(position.get("quantity")),
        "premium_received": premium_received,
        "cash_required": cash_required,
        "breakeven_price": number_or_none(position.get("breakeven_price")),
        "market_value": number_or_none(position.get("market_value")),
        "unrealized_pnl": unrealized_pnl,
        "current_option_price": number_or_none(position.get("current_price")),
        "average_entry_price": number_or_none(position.get("average_entry_price")),
        "days_to_expiration": days_to_expiration(position.get("expiration")),
        "pnl_vs_premium_percent": percent_of(unrealized_pnl, premium_received),
        "pnl_vs_cash_required_percent": percent_of(unrealized_pnl, cash_required),
        "financial_status": classify_financial_status(position),
        "assignment_status": classify_assignment_status(position),
        "assignment_acceptability": "unknown",
        "timing_quality": classify_timing_quality(position),
        "lesson_type": classify_lesson_type(position),
        "source": position.get("source", "alpaca"),
    }


## Summarize one snapshot in plain language for quick debugging and future UI use.
## The LLM layer will eventually produce richer explanations, but this gives
## HELIOS useful memory immediately without waiting on OpenAI calls.
def summarize_snapshot(snapshot):
    ticker = snapshot.get("ticker_symbol") or "This CSP"
    strike = snapshot.get("strike")
    pnl = snapshot.get("unrealized_pnl")
    financial_status = snapshot.get("financial_status", "unknown")
    assignment_status = snapshot.get("assignment_status", "unknown")
    lesson_type = snapshot.get("lesson_type", "insufficient_data")

    return (
        f"{ticker} {strike} put is currently {financial_status}; "
        f"unrealized P/L is {pnl}, assignment pressure looks {assignment_status}, "
        f"and the early lesson category is {lesson_type}."
    )
