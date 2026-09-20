## Covered call: sell an out-of-the-money call against 100 shares already owned.
##
## The shares are the collateral, so a covered call commits no buying power and
## is limited instead by how many uncovered 100-share lots the account holds. It
## follows the same thresholds as a cash-secured put, mirrored for calls, plus one
## rule of its own: the strike must sit at or above what the shares really cost,
## so being called away can never lock in a loss.

from functools import partial

from alpaca.trading.enums import ContractType

from backend.config import APPROVED_TICKERS, MIN_PATTERN_SAMPLE_SIZE, SHARES_PER_CONTRACT
from backend.memory.holdings import build_holdings
from backend.strategy.engine.option_chain import summarize_option_market
from backend.strategy.spec import OptionRules, OptionStrategy, ReviewConfig


KEY = "covered_call"
STORED_NAME = "covered call"

# A call this close to the money is more likely than not to be exercised.
LIKELY_CALLED_AWAY_OTM_PERCENT = 2.0

RULES = OptionRules(
    min_dte=30,
    max_dte=45,
    target_delta=0.25,
    delta_tolerance=0.05,
    max_spread=0.50,
    min_quote_size=1,
    min_iv_percent=20,
    max_iv_percent=80,
    min_roc_percent=0.50,
)

DISPLAY_COLUMNS = (
    "tickerSymbol",
    "contractSymbol",
    "expiration",
    "DTE",
    "strike",
    "currentStockPrice",
    "delta",
    "bid",
    "ask",
    "bidSize",
    "askSize",
    "spread",
    "ivPercent",
    "costBasis",
    "breakevenPrice",
    "premiumIfSoldAtBid",
    "maxProfitIfCalledAway",
    "returnOnCashPercent",
    "score",
)

STRATEGY_RULES = {
    "strategy": STORED_NAME,
    "approved_tickers": APPROVED_TICKERS,
    "target_delta": RULES.target_delta,
    "delta_tolerance": RULES.delta_tolerance,
    "min_dte": RULES.min_dte,
    "max_dte": RULES.max_dte,
    "max_spread": RULES.max_spread,
    "min_iv_percent": RULES.min_iv_percent,
    "max_iv_percent": RULES.max_iv_percent,
    "min_roc_percent": RULES.min_roc_percent,
    "shares_per_contract": SHARES_PER_CONTRACT,
    "strike_at_or_above_cost_basis": True,
    "minimum_pattern_sample_size": MIN_PATTERN_SAMPLE_SIZE,
}

# What the model should weigh that is specific to selling calls against owned shares.
REVIEW_GUIDANCE = """You are reviewing covered call candidates: selling a call against 100 shares the user already owns.

Covered calls suit shares the user is comfortable selling at the strike. A neutral-to-moderately-bullish
outlook is ideal, because the premium adds income while the shares are held. A strongly bullish outlook
argues against selling, since being called away caps the upside at the strike. A bearish outlook is not
solved by a covered call either, because the premium only partially offsets a falling stock.

Then evaluate whether selling each provided call is reasonable. Consider its strike, expiration, DTE,
delta, implied volatility, total premium, bid/ask spread, liquidity, recent price trend, the upside given
up above the strike, and the likelihood of being called away. Every candidate's strike already sits at or
above the user's real cost basis, so being called away cannot lock in a loss; compare how much profit each
strike would lock in if the shares are called away. Distinguish contracts on the same ticker by their
individual terms.

Before recommending, consider the user's current portfolio and whether selling these shares at the strike
fits it. A covered call adds no new market exposure, because the shares are already owned, but it does
cap their upside and may end the position. If the shares came from an assigned cash-secured put, this is
the second half of the wheel strategy: the aim is to collect premium while exiting at a defensible price,
not to hold indefinitely.

Treat being called away as an acceptable outcome, not a failure, when the strike is at or above cost basis.
Maximum profit is the premium plus the gain from cost basis to the strike, and it occurs when the shares are
called away at expiration. Do not confuse the largest premium with the best trade: a strike close to the
current price earns more premium but gives up more upside.
"""


## Turn one call quote into the economics of selling it against owned shares.
##
## returnOnCashPercent keeps the engine's shared column name, but here it measures
## premium against the market value of the shares being encumbered, since the
## shares rather than cash are the capital at risk. Breakeven and the called-away
## profit use the real cost basis, so they include premium already collected.
def economics(strike, bid, current_stock_price, dte, cost_basis):
    premium_if_sold_at_bid = bid * SHARES_PER_CONTRACT
    return_on_shares = premium_if_sold_at_bid / (current_stock_price * SHARES_PER_CONTRACT)

    return {
        "percentOTM": ((strike - current_stock_price) / current_stock_price) * 100,
        "costBasis": cost_basis,
        "breakevenPrice": cost_basis - bid,
        "premiumIfSoldAtBid": premium_if_sold_at_bid,
        "maxProfitIfCalledAway": (strike - cost_basis) * SHARES_PER_CONTRACT + premium_if_sold_at_bid,
        "returnOnCashPercent": return_on_shares * 100,
        "annualizedReturnPercent": return_on_shares * (365 / dte) * 100 if dte > 0 else None,
    }


## Tie the economics to one ticker's real cost basis before the chain is scanned.
## Only eligible tickers are scanned, so a holding record always exists here.
def bind_economics(ticker_symbol, portfolio_context):
    holding = portfolio_context["holdings"][ticker_symbol]

    return partial(economics, cost_basis=holding["cost_basis"])


## Confirm the shares that would cover this call are really held and still free, then price it against them.
##
## The scan's view of the account is already minutes old by the time a user
## clicks, and shares can be sold, called away, or committed to another call in
## between. Every number is therefore recounted from live broker state: shares
## held now, shares already committed to an open short call, and shares an
## unfilled sell order would commit if it fills. Without this check an order
## would be a naked call, which carries unlimited loss.
def secure_candidate(candidate, context):
    ticker_symbol = candidate["tickerSymbol"]
    holding = build_holdings(context.user_id, context.positions).get(ticker_symbol)
    if holding is None:
        raise ValueError(
            f"The connected account holds no {ticker_symbol} shares, "
            "and a covered call must be covered by shares that are actually owned."
        )

    pending_shares = SHARES_PER_CONTRACT * sum(
        abs(int(order.get("qty") or 1))
        for order in context.active_sell_orders
        if order["contract"]["option_type"] == "call"
        and order["contract"]["ticker_symbol"] == ticker_symbol
    )
    free_shares = holding["uncovered_shares"] - pending_shares
    if free_shares < SHARES_PER_CONTRACT:
        raise ValueError(
            f"Covering this call needs {SHARES_PER_CONTRACT} {ticker_symbol} shares that are not already "
            f"committed, but only {max(free_shares, 0):,.0f} of the {holding['shares']:,.0f} shares held are free."
        )

    # Re-checked here because the strike is only safe relative to a cost basis that can move:
    # buying more shares raises it, and a newly assigned put lowers it.
    cost_basis = holding["cost_basis"]
    strike = float(candidate["strike"])
    if strike < cost_basis:
        raise ValueError(
            f"The ${strike:,.2f} strike is below the ${cost_basis:,.2f} these {ticker_symbol} shares really cost, "
            "so being called away would lock in a loss."
        )

    return partial(economics, cost_basis=cost_basis)


## Reject any strike below what the shares really cost.
## Being called away below cost basis would turn a premium strategy into a guaranteed realized loss.
def strike_at_or_above_cost_basis(contracts):
    return contracts[contracts["strike"] >= contracts["costBasis"]]


## A ticker qualifies only when the account holds at least one uncovered 100-share lot of an approved stock.
## Approved-universe order is kept so scans run in a stable, repeatable sequence.
def eligible_tickers(portfolio_context=None):
    holdings = (portfolio_context or {}).get("holdings") or {}

    return [
        ticker
        for ticker in APPROVED_TICKERS
        if (holdings.get(ticker) or {}).get("uncovered_shares", 0) >= SHARES_PER_CONTRACT
    ]


## Create a compact numeric summary of one covered call candidate for the LLM.
## Cost basis and the called-away profit are included because they, not cash required, decide whether the trade is sound.
def summarize_candidate(candidate):
    return {
        **summarize_option_market(candidate),
        "cost_basis": float(candidate.costBasis),
        "breakeven_price": float(candidate.breakevenPrice),
        "max_profit_if_called_away": float(candidate.maxProfitIfCalledAway),
        "return_on_shares_percent": float(candidate.returnOnCashPercent),
    }


## Produce a deterministic recommendation when OpenAI is unavailable.
## The fallback still respects every hard rule, because it only chooses among candidates that already passed them.
def local_review(ticker_symbol, candidates):
    if candidates.empty:
        return {
            "decision": "reject_all",
            "selected_contract": None,
            "summary": "No covered calls passed the hard filters.",
            "risk_note": "No strike above the shares' cost basis met the premium, delta, and liquidity rules today.",
            "candidate_reviews": [],
            "review_source": "local_fallback",
        }

    best_candidate = candidates.iloc[0]
    percent_otm = (
        (best_candidate["strike"] - best_candidate["currentStockPrice"])
        / best_candidate["currentStockPrice"]
    ) * 100
    risk_notes = []

    if percent_otm <= LIKELY_CALLED_AWAY_OTM_PERCENT:
        risk_notes.append(
            "The strike is close to the current price, so the shares are fairly likely to be called away."
        )

    if best_candidate["ivPercent"] >= 50:
        risk_notes.append(
            "IV is high, which improves premium but may signal a larger expected move."
        )

    if not risk_notes:
        risk_notes.append("Primary risk is giving up upside above the strike if the shares are called away.")

    return {
        "decision": "approve",
        "selected_contract": best_candidate["contractSymbol"],
        "summary": (
            f"The top candidate is a {best_candidate['tickerSymbol']} covered call with the best current balance of "
            "target delta, premium, spread, and distance above cost basis among the filtered choices."
        ),
        "risk_note": " ".join(risk_notes),
        "candidate_reviews": [{
            "contract_symbol": best_candidate["contractSymbol"],
            "verdict": "approve",
            "market_context": "Live market evidence was unavailable to the local fallback.",
            "trade_rationale": "This contract ranked highest under the deterministic covered call rules.",
            "key_risk": "The shares may be called away at the strike, capping further upside.",
        }],
        "review_source": "local_fallback",
    }


COVERED_CALL = OptionStrategy(
    key=KEY,
    short_label="covered call",
    stored_name=STORED_NAME,
    contract_type=ContractType.CALL,
    rules=RULES,
    capital_column=None,
    collateral_basis_column="costBasis",
    display_columns=DISPLAY_COLUMNS,
    economics=economics,
    eligible_tickers=eligible_tickers,
    strategy_rules=STRATEGY_RULES,
    eligibility_requirement="at least 100 uncovered shares of an approved ticker",
    secure_candidate=secure_candidate,
    review=ReviewConfig(
        guidance=REVIEW_GUIDANCE,
        summarize_candidate=summarize_candidate,
        local_review=local_review,
    ),
    bind_economics=bind_economics,
    extra_filters=(strike_at_or_above_cost_basis,),
)
