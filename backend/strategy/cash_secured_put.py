## Cash-secured put: sell an out-of-the-money put backed by enough cash to buy the shares.
##
## Everything specific to this strategy lives here. Its thresholds, the economics
## that turn a quote into a trade worth judging, how it describes a candidate to
## the model, and the review guidance the model receives. The scan machinery it
## runs on is shared and knows none of this.

import json

from alpaca.trading.enums import ContractType

from backend.config import (
    APPROVED_TICKERS,
    CAPITAL_BUDGETS,
    MAX_OPEN_POSITIONS,
    MIN_PATTERN_SAMPLE_SIZE,
    OPENAI_CSP_MAX_OUTPUT_TOKENS,
)
from backend.market.prompt_context import (
    compact_market_context,
    compact_memory_context,
    compact_portfolio_context,
)
from backend.strategy.spec import OptionRules, OptionStrategy, ReviewConfig


KEY = "cash_secured_put"

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
    "strategy": "cash-secured put",
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


## Turn one put quote into the economics of selling it cash-secured.
## The cash required is the full cost of buying the shares at the strike, which is what makes the put "secured".
def economics(strike, bid, current_stock_price, dte):
    cash_required = strike * 100
    premium_if_sold_at_bid = bid * 100
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
        "ticker_symbol": candidate.tickerSymbol,
        "contract_symbol": candidate.contractSymbol,
        "expiration": candidate.expiration,
        "dte": int(candidate.DTE),
        "strike": float(candidate.strike),
        "current_stock_price": float(candidate.currentStockPrice),
        "delta": float(candidate.delta),
        "iv_percent": float(candidate.ivPercent),
        "bid": float(candidate.bid),
        "ask": float(candidate.ask),
        "spread": float(candidate.spread),
        "bid_size": int(getattr(candidate, "bidSize", 0) or 0),
        "ask_size": int(getattr(candidate, "askSize", 0) or 0),
        "premium": float(candidate.premiumIfSoldAtBid),
        "cash_required": float(candidate.cashRequired),
        "breakeven_price": float(candidate.breakevenPrice),
        "return_on_cash_percent": float(candidate.returnOnCashPercent),
    }


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


## Build the CSP-review prompt sent to OpenAI.
## It instructs the model to review only supplied candidates, consider reputable context, and return structured JSON.
def build_prompt(
    ticker_symbol,
    candidates,
    strategy_rules,
    market_context=None,
    portfolio_context=None,
    memory_context=None,
):
    candidate_summaries = [
        summarize_candidate(candidate)
        for candidate in candidates.itertuples()
    ]
    market_evidence = compact_market_context(market_context)
    portfolio_evidence = compact_portfolio_context(portfolio_context)
    memory_evidence = compact_memory_context(memory_context)

    return f"""
You are reviewing cash-secured put candidates for an educational paper-trading prototype.

Important rules:
- The candidates already passed hard-coded filters.
- You may approve, reject, or mark the recommendation needs_review.
- You may not suggest contracts outside the provided candidates or tickers.
- You may not override the strategy rules.
- This is not financial advice and no order will be placed by you, however you may recommend a top choice as you see fit.
- Be concise and practical for a beginner learning CSPs.
- Primarily use supplied evidence. If additional evidence is supplied by the system,
  only use evidence from pre-approved or accredited sources such as Reuters, Bloomberg,
  WSJ, Financial Times, AP, CNBC, official company releases, earnings reports, or SEC filings.
  Do not invent current events.
- If relevant news or earnings evidence is absent, say so instead of inventing it.
- Treat earnings as released only when the supplied headline or summary confirms a release;
  do not describe previews, estimates, or upcoming reports as completed results. However, you may use the
  estimates or previews to discuss risk and potential volatility and assess how they may affect the stock or option
  during its lifetime.

Review every provided contract. For each candidate, use relevant company news and earnings
from the supplied 10-day context and explain how those events could help or hurt the stock
during the option's lifetime through expiration. Compare those company-specific factors with
the recent ticker trend and the broader SPY, QQQ, and IWM market trends.

Include macroeconomic and geopolitical developments, recent past and present, in your context for recommending CSPs
as they may affect the candidate during the option's lifetime. 
Analyze them through market transmission channels, not political opinion: energy and commodity prices, inflation and interest rates, currencies,
consumer and business demand, government spending, tariffs and sanctions, supply chains,
regional revenue exposure, and overall investor risk appetite. Explain which channels actually
apply to each ticker; do not assume the same event helps or hurts every company equally.

Distinguish a verified event from a possible scenario, identify uncertainty, and do not invent
country exposure or causal effects that are absent from the supplied evidence.
Give greater weight to established reporting and corroborated events. Treat a single unrated,
opinion-based, or speculative headline as weak evidence and do not base a recommendation on it.
Use the supplied article fields:
- source_quality tells you how much confidence to place in the source.
- tags identify catalysts such as layoffs, earnings, guidance, AI, regulation, macro, and geopolitical risk.
- why_it_matters is a short pre-classified reason the article may matter for CSP risk.
If a candidate ticker has layoffs, restructuring, weak guidance, regulation, earnings surprise,
or geopolitical exposure in the supplied evidence, explicitly discuss whether the extra premium
is compensation for risk that may be too high.

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
by a lot, user implements wheel strategy and sells said shares))). If the user has multiple positions in the same sector, consider
whether the new CSP would increase sector concentration risk and furthermore create losses for the user.

Treat assignment as an acceptable fallback, not the preferred source of profit. Recommend a CSP
only when the strike minus premium is a defensible effective purchase price and the available
evidence supports being willing to own 100 shares even if the stock falls further after assignment.
Remember that maximum CSP profit is limited to the premium and normally occurs when the put
expires worthless; do not confuse maximum premium with the best risk-adjusted trade.

Use prior user decisions only when they show a repeated preference. Never claim to have learned
a repeated pattern until the supplied pattern sample_size reaches its minimum_sample_size, and never let a preference override strategy or capital rules.
Treat explicit trade feedback as a direct statement about that user's experience, even when only
one response exists, but do not turn one response into a general performance pattern. Keep measured
P/L separate from satisfaction: a user may welcome assignment despite an option loss, or dislike a
profitable trade because its risk or sizing was uncomfortable. Outcome-review drivers are reasoned
interpretations rather than guaranteed causation, so respect each driver's evidence_strength and
the listed uncertainties.
Select the strongest supplied contract, mark the result needs_review, or reject all. Explain why
the selected contract is better suited to the current market than the other candidates.

Ticker:
{ticker_symbol}

Strategy rules:
{json.dumps(strategy_rules, indent=2)}

Candidate CSPs:
{json.dumps(candidate_summaries, indent=2)}

Ten-day company news, earnings, and market trends:
{json.dumps(market_evidence, separators=(",", ":"))}

Current portfolio and capital context:
{json.dumps(portfolio_evidence, separators=(",", ":"))}

Retrieved long-term memory:
{json.dumps(memory_evidence, separators=(",", ":"))}

Memory rules:
- Treat realized trade outcomes as facts, but candidate observations as counterfactual evidence.
- Treat user feedback as explicit preference evidence, not as proof that a trade was financially good or bad.
- Use portfolio-wide lessons for recurring trade-structure risk even when the next candidate has a different ticker.
- Treat post-trade driver explanations as hypotheses bounded by their evidence strength, not established causation.
- Do not claim a repeated preference or outcome pattern before its supplied minimum sample size is met.
- State when memory is insufficient and rely on current evidence plus hard strategy rules.
- Never let remembered preferences override affordability, position limits, or safety filters.

Return JSON only.
"""


CASH_SECURED_PUT = OptionStrategy(
    key=KEY,
    short_label="CSP",
    stored_name="cash-secured put",
    contract_type=ContractType.PUT,
    rules=RULES,
    capital_column="cashRequired",
    display_columns=DISPLAY_COLUMNS,
    economics=economics,
    eligible_tickers=eligible_tickers,
    strategy_rules=STRATEGY_RULES,
    review=ReviewConfig(
        agent_description=(
            "You are a cautious CSP review agent. "
            "Review only the provided candidates and return structured JSON."
        ),
        schema_name="csp_review",
        cache_key="helios-csp-review-v1",
        max_output_tokens=OPENAI_CSP_MAX_OUTPUT_TOKENS,
        build_prompt=build_prompt,
        summarize_candidate=summarize_candidate,
        local_review=local_review,
    ),
)
