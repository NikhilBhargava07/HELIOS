## Cash-secured put: sell an out-of-the-money put backed by enough cash to buy the shares.
##
## Everything specific to this strategy lives here. Its thresholds, the economics
## that turn a quote into a trade worth judging, how it describes a candidate to
## the model, and the review guidance the model receives. The scan machinery it
## runs on is shared and knows none of this.

from alpaca.trading.enums import ContractType

from backend.capital import strategy_capacity
from backend.config import (
    APPROVED_TICKERS,
    CAPITAL_BUDGETS,
    MAX_OPEN_POSITIONS,
    MIN_PATTERN_SAMPLE_SIZE,
    SHARES_PER_CONTRACT,
)
from backend.strategy.engine.candidates import find_option_candidates
from backend.strategy.engine.option_chain import summarize_option_market
from backend.strategy.spec import OptionRules, OptionStrategy, ReviewConfig


KEY = "cash_secured_put"
STORED_NAME = "cash-secured put"

# A return this far above normal usually means the market is pricing in real trouble.
HIGH_ROC_WARNING_PERCENT = 2.00

RULES = OptionRules(
    min_dte=30,
    max_dte=45,
    target_delta=-0.25,
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
    "breakevenPrice",
    "premiumIfSoldAtBid",
    "cashRequired",
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
    "max_csp_capital_percent": CAPITAL_BUDGETS[KEY],
    "max_open_positions": MAX_OPEN_POSITIONS,
    "minimum_pattern_sample_size": MIN_PATTERN_SAMPLE_SIZE,
}

# What the model should weigh that is specific to selling puts against cash.
# Evidence standards, macro analysis, and memory discipline are shared and live in review_prompt.py.
REVIEW_GUIDANCE = """You are reviewing cash-secured put candidates.

Prefer CSPs on companies with a neutral-to-moderately-bullish outlook: the shares have been
relatively stable, moderately trending upward, or experiencing a controlled short-term pullback
while the longer-term company outlook remains intact. A down day or pullback may increase put
premium, but higher premium alone never makes a CSP attractive. Distinguish a temporary pullback
from a sustained downtrend, weakening fundamentals, or damaging news; reject or flag the trade
when the premium appears to be compensation for unacceptable downside risk.

Then evaluate whether selling each provided CSP is reasonable. Consider its strike,
expiration, DTE, delta, implied volatility, total premium, breakeven, bid/ask spread,
liquidity, recent price trend, assignment risk, cash required, return on cash, and whether
owning 100 shares at the strike would be reasonable. Distinguish contracts on the same ticker
by their individual terms.

Before recommending to the user, evaluate the company's current state in the market, the general
market trend, and the user's current portfolio. Consider whether the user has sufficient capital
to cover the cash-secured put, whether the user already has a position in the same ticker,
and whether the user is in a bad position to take on more risk. If the user already has a position in the same ticker,
consider whether the new CSP would be a reasonable addition to the existing position or whether
it would increase risk exposure (likely, if the ticker is doing poorly, it is not a great idea
to recommend the user another CSP for that ticker. UNLESS YOU SEE EVIDENCE OF A POSITIVE OUTLOOK OR THAT THERE IS
A POSITIVE PATTERN IN THE USER'S DECISIONS WITH THE TICKER (positive pattern = gaining money, shares held increases
by a lot, user implements wheel strategy and sells said shares)). If the user has multiple positions in the same sector, consider
whether the new CSP would increase sector concentration risk and furthermore create losses for the user.

Treat assignment as an acceptable fallback, not the preferred source of profit. Recommend a CSP
only when the strike minus premium is a defensible effective purchase price and the available
evidence supports being willing to own 100 shares even if the stock falls further after assignment.
Remember that maximum CSP profit is limited to the premium and normally occurs when the put
expires worthless; do not confuse maximum premium with the best risk-adjusted trade.
"""


## Turn one put quote into the economics of selling it cash-secured.
## The cash required is the full cost of buying the shares at the strike, which is what makes the put "secured".
def economics(strike, bid, current_stock_price, dte):
    cash_required = strike * SHARES_PER_CONTRACT
    premium_if_sold_at_bid = bid * SHARES_PER_CONTRACT
    return_on_cash = premium_if_sold_at_bid / cash_required

    return {
        "percentOTM": ((current_stock_price - strike) / current_stock_price) * 100,
        "breakevenPrice": strike - bid,
        "cashRequired": cash_required,
        "premiumIfSoldAtBid": premium_if_sold_at_bid,
        "returnOnCashPercent": return_on_cash * 100,
        "annualizedReturnPercent": return_on_cash * (365 / dte) * 100 if dte > 0 else None,
    }


## Every approved ticker is a candidate, because selling a put requires only cash.
## Strategies that need an existing holding narrow this list against the portfolio instead.
def eligible_tickers(portfolio_context=None):
    return APPROVED_TICKERS


## Create a compact numeric summary of one CSP candidate for the LLM.
## The model receives only the fields it needs to compare risk, reward, and assignment context.
def summarize_candidate(candidate):
    return {
        **summarize_option_market(candidate),
        "cash_required": float(candidate.cashRequired),
        "breakeven_price": float(candidate.breakevenPrice),
        "return_on_cash_percent": float(candidate.returnOnCashPercent),
    }


## Confirm against live broker state that this put can still be secured with cash.
##
## The scan's capital view is already minutes old by the time a user clicks, and
## an unfilled sell order commits its cash just as an open position does, so both
## the position count and the committed cash are recounted here. Selling a put is
## the same trade whatever cash backs it, so the economics need no binding.
def secure_candidate(candidate, context):
    open_puts = [
        position for position in context.positions
        if position.get("strategy") == STORED_NAME
    ]
    pending_puts = [
        order for order in context.active_sell_orders
        if order["contract"]["option_type"] == "put"
    ]
    if len(open_puts) + len(pending_puts) >= MAX_OPEN_POSITIONS:
        raise ValueError(
            f"The {MAX_OPEN_POSITIONS}-position CSP limit includes pending orders and has been reached."
        )

    committed = sum(float(position.get("cash_required") or 0) for position in open_puts)
    _, strategy_available = strategy_capacity(
        context.total_capital,
        CAPITAL_BUDGETS[KEY],
        committed,
    )
    broker_available = context.account.get("available_csp_cash")
    if broker_available is None:
        raise ValueError("Alpaca did not report options buying power, so HELIOS cannot verify this CSP safely.")

    available_cash = min(strategy_available, broker_available)
    cash_required = float(candidate.get("cashRequired") or 0)
    if cash_required > available_cash:
        raise ValueError(
            f"This CSP requires ${cash_required:,.2f}, but current strategy and broker limits allow ${available_cash:,.2f}."
        )

    return economics


## Produce a deterministic recommendation when OpenAI is unavailable.
## The fallback keeps the app usable for demonstrations while still respecting hard strategy rules.
def local_review(ticker_symbol, candidates):
    if candidates.empty:
        return {
            "decision": "reject_all",
            "selected_contract": None,
            "summary": "No candidates passed the hard CSP filters.",
            "risk_note": "Try another approved ticker or loosen filters only after understanding the tradeoff.",
            "candidate_reviews": [],
            "review_source": "local_fallback",
        }

    best_candidate = candidates.iloc[0]
    risk_notes = []

    if best_candidate["returnOnCashPercent"] >= HIGH_ROC_WARNING_PERCENT:
        risk_notes.append(
            "ROC is elevated, so inspect news, earnings, and downside risk before selling."
        )

    if best_candidate["ivPercent"] >= 50:
        risk_notes.append(
            "IV is high, which improves premium but may signal a larger expected move."
        )

    if not risk_notes:
        risk_notes.append("Primary risk is assignment if the stock falls below the strike.")

    ticker_display = best_candidate["tickerSymbol"] if "tickerSymbol" in best_candidate else ticker_symbol

    return {
        "decision": "approve",
        "selected_contract": best_candidate["contractSymbol"],
        "summary": (
            f"The top candidate is a {ticker_display} CSP with the best current balance of "
            "target delta, premium, spread, and breakeven among the filtered choices."
        ),
        "risk_note": " ".join(risk_notes),
        "candidate_reviews": [{
            "contract_symbol": best_candidate["contractSymbol"],
            "verdict": "approve",
            "market_context": "Live market evidence was unavailable to the local fallback.",
            "trade_rationale": "This contract ranked highest under the deterministic CSP rules.",
            "key_risk": "Assignment remains possible if the stock falls below the strike.",
        }],
        "review_source": "local_fallback",
    }


CASH_SECURED_PUT = OptionStrategy(
    key=KEY,
    short_label="CSP",
    stored_name=STORED_NAME,
    contract_type=ContractType.PUT,
    rules=RULES,
    capital_column="cashRequired",
    collateral_basis_column=None,
    candidate_id_column="contractSymbol",
    display_columns=DISPLAY_COLUMNS,
    find_candidates=find_option_candidates,
    rank_column="score",
    economics=economics,
    eligible_tickers=eligible_tickers,
    strategy_rules=STRATEGY_RULES,
    eligibility_requirement="enough available cash to secure the put",
    secure_candidate=secure_candidate,
    review=ReviewConfig(
        guidance=REVIEW_GUIDANCE,
        summarize_candidate=summarize_candidate,
        local_review=local_review,
    ),
)
