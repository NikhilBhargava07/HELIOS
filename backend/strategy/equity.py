## Stock recommendation: judge whether an approved stock is worth owning, and never trade it.
##
## HELIOS advises on stocks and stops there. Nothing here can place an order, and
## secure_candidate refuses by design rather than by omission, so the refusal
## cannot be lost to a later refactor.
##
## This strategy is deliberately thinner than the option ones, and the reason is
## worth stating: a cash-secured put can be gated on delta, spread, implied
## volatility, and return, because a contract has structure to measure. A share
## has no expiry, no strike, and no premium. The only hard rules available are
## the approved universe and the presence of real price history, so the judgment
## is the model's and the protection is that HELIOS will not act on it.

import pandas as pd

from backend.config import APPROVED_TICKERS, MIN_PATTERN_SAMPLE_SIZE
from backend.market.trends import get_market_trends
from backend.strategy.spec import ReviewConfig, ScanResult, Strategy


KEY = "equity"
STORED_NAME = "stock"

# The trend windows the model compares, newest move first.
TREND_WINDOWS = ("1d", "5d", "1m", "ytd")

DISPLAY_COLUMNS = (
    "tickerSymbol",
    "currentStockPrice",
    "percentChange1Day",
    "percentChange5Day",
    "percentChange1Month",
    "percentChangeYTD",
    "sharesHeld",
    "costBasis",
    "unrealizedReturnPercent",
)

STRATEGY_RULES = {
    "strategy": STORED_NAME,
    "approved_tickers": APPROVED_TICKERS,
    # Stated to the model so it never phrases a recommendation as an order HELIOS will place.
    "action_taken": "none",
    "advisory_only": True,
    "trend_windows": list(TREND_WINDOWS),
    "minimum_pattern_sample_size": MIN_PATTERN_SAMPLE_SIZE,
}

# What the model should weigh that is specific to owning shares outright.
REVIEW_GUIDANCE = """You are reviewing stocks the user may want to own, and HELIOS will not place any stock order.
Your review is information for the user to act on themselves, so say plainly what you would do and why.

Judge each ticker as a business to own rather than as a price that moved. A stock that fell is not
automatically cheap, and a stock that rose is not automatically strong. Explain what the move appears
to reflect, and say when the evidence does not support a confident read.

Shares held and cost basis are included when the user already owns the stock. For a holding, consider
whether adding, holding, or trimming is the better answer, and weigh the unrealized return against what
the position now represents in the portfolio. For a stock the user does not own, consider whether starting
a position is justified today rather than merely defensible in general.

Unlike an option, a share has no expiration and no premium, so there is no structural rule protecting this
trade. Say so when your view rests on judgment rather than measurable evidence, and prefer recommending
nothing over recommending something weakly supported. Concentration matters: consider what the user already
owns, including shares held against covered calls and cash committed to puts on the same ticker or sector.
"""


## Return every approved ticker, since owning a stock requires nothing but cash the user controls.
## The universe is the hard rule here: no ticker outside it can ever be recommended.
def eligible_tickers(portfolio_context=None):
    return APPROVED_TICKERS


## Describe one ticker's price, recent moves, and the user's existing position in it.
## Unrealized return is reported only for a holding, because there is nothing to measure against otherwise.
def build_candidate_row(ticker_symbol, price, trend, holding):
    shares = (holding or {}).get("shares")
    cost_basis = (holding or {}).get("cost_basis")

    return {
        "tickerSymbol": ticker_symbol,
        "currentStockPrice": price,
        "percentChange1Day": trend.get("1d"),
        "percentChange5Day": trend.get("5d"),
        "percentChange1Month": trend.get("1m"),
        "percentChangeYTD": trend.get("ytd"),
        "sharesHeld": shares,
        "costBasis": cost_basis,
        "unrealizedReturnPercent": (
            ((price - cost_basis) / cost_basis) * 100
            if shares and cost_basis and price
            else None
        ),
    }


## Build one row per approved ticker from a single batch of price history.
##
## Every ticker's trend comes from one broker request, so unlike an option scan
## there is nothing to loop over and nothing to fail per ticker. A ticker whose
## price or history is missing is dropped rather than shown with blanks, because
## the model would otherwise be judging a stock it cannot actually see.
def find_candidates(strategy, ticker_symbols, context):
    try:
        trends = get_market_trends(
            list(ticker_symbols),
            periods=TREND_WINDOWS,
            stock_data_client=context.stock_data_client,
        )
    except Exception as error:
        return ScanResult(candidates=pd.DataFrame(), errors=(f"trends:{type(error).__name__}",))

    trends_by_ticker = {trend["ticker"]: trend for trend in trends}
    holdings = (context.portfolio_context or {}).get("holdings") or {}
    rows = []
    errors = []

    for ticker_symbol in ticker_symbols:
        price = (context.latest_prices.get(ticker_symbol) or {}).get("price")
        trend = trends_by_ticker.get(ticker_symbol)
        if price is None or trend is None or trend.get("1d") is None:
            errors.append(f"{ticker_symbol}:no_price_history")
            continue

        rows.append(build_candidate_row(ticker_symbol, price, trend, holdings.get(ticker_symbol)))

    return ScanResult(
        candidates=pd.DataFrame(rows, columns=list(DISPLAY_COLUMNS)) if rows else pd.DataFrame(),
        errors=tuple(errors),
    )


## Create a compact numeric summary of one stock for the LLM.
## The user's own position is included because holding a stock and buying it are different questions.
def summarize_candidate(candidate):
    return {
        "ticker_symbol": candidate.tickerSymbol,
        "current_stock_price": float(candidate.currentStockPrice),
        "percent_change_1d": _number_or_none(candidate.percentChange1Day),
        "percent_change_5d": _number_or_none(candidate.percentChange5Day),
        "percent_change_1m": _number_or_none(candidate.percentChange1Month),
        "percent_change_ytd": _number_or_none(candidate.percentChangeYTD),
        "shares_held": _number_or_none(candidate.sharesHeld),
        "cost_basis": _number_or_none(candidate.costBasis),
        "unrealized_return_percent": _number_or_none(candidate.unrealizedReturnPercent),
    }


## Convert a possibly missing trend value into a plain number.
## Missing history stays null in the prompt so the model can see what it does not know.
def _number_or_none(value):
    return None if value is None or pd.isna(value) else float(value)


## Decline to recommend a stock when the model is unavailable.
##
## The option strategies can fall back on their own rules, because a contract that
## passed every hard filter is already defensible. A stock has no such filter to
## pass, so a deterministic pick here would be an opinion HELIOS cannot support.
def local_review(ticker_symbol, candidates):
    return {
        "decision": "reject_all",
        "selected_contract": None,
        "summary": "Stock recommendations need the review model, which is unavailable right now.",
        "risk_note": (
            "Unlike an option, a stock has no hard rules to fall back on, so HELIOS will not "
            "name a stock to buy without a model review. Current prices and trends are still shown."
        ),
        "candidate_reviews": [],
        "review_source": "local_fallback",
    }


## Refuse to place a stock order, because HELIOS only advises on stocks.
## The refusal is explicit so that wiring a future order path has to be a deliberate decision.
def secure_candidate(candidate, context):
    raise ValueError(
        "HELIOS does not place stock orders. This is a recommendation to act on yourself, "
        "and no order was sent."
    )


EQUITY = Strategy(
    key=KEY,
    short_label="stock recommendation",
    stored_name=STORED_NAME,
    capital_column=None,
    collateral_basis_column=None,
    candidate_id_column="tickerSymbol",
    display_columns=DISPLAY_COLUMNS,
    eligible_tickers=eligible_tickers,
    find_candidates=find_candidates,
    strategy_rules=STRATEGY_RULES,
    eligibility_requirement="an approved ticker with readable price history",
    secure_candidate=secure_candidate,
    # Ranking stocks would mean choosing momentum or value as a house view. The model
    # ranks them with reasons instead, so every approved ticker is shown to it.
    rank_column=None,
    max_candidates=None,
    review=ReviewConfig(
        guidance=REVIEW_GUIDANCE,
        summarize_candidate=summarize_candidate,
        local_review=local_review,
    ),
)
