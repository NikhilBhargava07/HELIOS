## Review hard-filtered CSP candidates with OpenAI or a local fallback.

import json
import logging
import os

from backend.config import OPENAI_MODEL


logger = logging.getLogger(__name__)


HIGH_ROC_WARNING_PERCENT = 2.00

CSP_REVIEW_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "decision": {
            "type": "string",
            "enum": ["approve", "reject_all", "needs_review"],
        },
        "selected_contract": {
            "type": ["string", "null"],
        },
        "summary": {
            "type": "string",
        },
        "risk_note": {
            "type": "string",
        },
        "candidate_reviews": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "contract_symbol": {"type": "string"},
                    "verdict": {
                        "type": "string",
                        "enum": ["approve", "needs_review", "reject"],
                    },
                    "market_context": {"type": "string"},
                    "trade_rationale": {"type": "string"},
                    "key_risk": {"type": "string"},
                },
                "required": [
                    "contract_symbol", "verdict", "market_context",
                    "trade_rationale", "key_risk",
                ],
            },
        },
    },
    "required": [
        "decision", "selected_contract", "summary", "risk_note",
        "candidate_reviews",
    ],
}


## Convert one DataFrame candidate row into compact AI input.
def build_candidate_summary(candidate):
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


## Convert all filtered candidates into JSON-friendly AI input.
def prepare_candidates_for_ai(candidates):
    return [
        build_candidate_summary(candidate)
        for candidate in candidates.itertuples()
    ]


## Use deterministic fallback when OpenAI is unavailable.
def local_review_csp_candidates(ticker_symbol, candidates):
    if candidates.empty:
        return {
            "decision": "reject_all",
            "selected_contract": None,
            "summary": "No candidates passed the hard CSP filters.",
            "risk_note": "Try another approved ticker or loosen filters only after understanding the tradeoff.",
            "candidate_reviews": [],
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
    }


## Build a candidate-centered prompt grounded in supplied market evidence.
def build_ai_prompt(
    ticker_symbol,
    candidates,
    strategy_rules,
    market_context=None,
    portfolio_context=None,
    memory_context=None,
):
    candidate_summaries = prepare_candidates_for_ai(candidates)

    return f"""
You are reviewing cash-secured put candidates for an educational paper-trading prototype.

Important rules:
- The candidates already passed hard-coded filters.
- You may approve, reject all, or mark the recommendation needs_review.
- You may not suggest contracts outside the provided candidates or tickers.
- You may not override the strategy rules.
- This is not financial advice and no order will be placed.
- Be concise and practical for a beginner learning CSPs.
- Use only the supplied evidence. Do not claim that you searched independently.
- If relevant news or earnings evidence is absent, say so instead of inventing it.
- Treat earnings as released only when the supplied headline or summary confirms a release;
  do not describe previews, estimates, or upcoming reports as completed results.

Review every provided contract. For each candidate, use relevant company news and earnings
from the supplied 10-day context and explain how those events could help or hurt the stock
during the option's lifetime through expiration. Compare those company-specific factors with
the recent ticker trend and the broader SPY, QQQ, and IWM market trends.

Include macroeconomic and geopolitical developments when they could materially affect the
candidate during the option's lifetime. Analyze them through market transmission channels,
not political opinion: energy and commodity prices, inflation and interest rates, currencies,
consumer and business demand, government spending, tariffs and sanctions, supply chains,
regional revenue exposure, and overall investor risk appetite. Explain which channels actually
apply to each ticker; do not assume the same event helps or hurts every company equally.
Distinguish a verified event from a possible scenario, identify uncertainty, and do not invent
country exposure or causal effects that are absent from the supplied evidence.
Give greater weight to established reporting and corroborated events. Treat a single unrated,
opinion-based, or speculative headline as weak evidence and do not base a recommendation on it.

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
it would increase risk exposure. If the user has multiple positions in the same sector, consider
whether the new CSP would increase sector concentration risk.

Treat assignment as an acceptable fallback, not the preferred source of profit. Recommend a CSP
only when the strike minus premium is a defensible effective purchase price and the available
evidence supports being willing to own 100 shares even if the stock falls further after assignment.
Remember that maximum CSP profit is limited to the premium and normally occurs when the put
expires worthless; do not confuse maximum premium with the best risk-adjusted trade.

Use prior user decisions only when they show a repeated preference. Never claim to have learned
a user pattern from sparse history (sparse history is < 10 past positions), and never let a preference override strategy or capital rules.
Select the strongest supplied contract, mark the result needs_review, or reject all. Explain why
the selected contract is better suited to the current market than the other candidates.

Ticker:
{ticker_symbol}

Strategy rules:
{json.dumps(strategy_rules, indent=2)}

Candidate CSPs:
{json.dumps(candidate_summaries, indent=2)}

Ten-day company news, earnings, and market trends:
{json.dumps(market_context or {}, indent=2)}

Current portfolio and capital context:
{json.dumps(portfolio_context or {}, indent=2)}

Retrieved long-term memory:
{json.dumps(memory_context or {}, indent=2)}

Memory rules:
- Treat realized trade outcomes as facts, but candidate observations as counterfactual evidence.
- Do not claim a user preference or outcome pattern when its evidence count is sparse.
- State when memory is insufficient and rely on current evidence plus hard strategy rules.
- Never let remembered preferences override affordability, position limits, or safety filters.

Return JSON only.
"""


## Request a schema-validated CSP review from OpenAI.
def openai_review_csp_candidates(
    ticker_symbol,
    candidates,
    strategy_rules,
    market_context=None,
    portfolio_context=None,
    memory_context=None,
):
    try:
        from openai import OpenAI
    except ImportError:
        review = local_review_csp_candidates(ticker_symbol, candidates)
        review["risk_note"] = (
            "OpenAI SDK is not installed yet, so local rule-based review was used. "
            + review["risk_note"]
        )
        return review

    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    prompt = build_ai_prompt(
        ticker_symbol,
        candidates,
        strategy_rules,
        market_context,
        portfolio_context,
        memory_context,
    )

    try:
        response = client.responses.create(
            model=OPENAI_MODEL,
            input=[
                {
                    "role": "system",
                    "content": (
                        "You are a cautious CSP review agent. "
                        "Review only the provided candidates and return structured JSON."
                    ),
                },
                {
                    "role": "user",
                    "content": prompt,
                },
            ],
            text={
                "format": {
                    "type": "json_schema",
                    "name": "csp_review",
                    "schema": CSP_REVIEW_SCHEMA,
                    "strict": True,
                }
            },
        )

        return json.loads(response.output_text)
    except Exception as error:
        logger.warning("OpenAI CSP review failed: %s", type(error).__name__)
        review = local_review_csp_candidates(ticker_symbol, candidates)
        review["risk_note"] = (
            "OpenAI review was unavailable, so local rule-based review was used. "
            + review["risk_note"]
        )
        return review


## Select OpenAI review when configured, otherwise use deterministic fallback.
def review_csp_candidates(
    ticker_symbol,
    candidates,
    strategy_rules,
    market_context=None,
    portfolio_context=None,
    memory_context=None,
):
    if not os.getenv("OPENAI_API_KEY"):
        return local_review_csp_candidates(ticker_symbol, candidates)

    return openai_review_csp_candidates(
        ticker_symbol,
        candidates,
        strategy_rules,
        market_context,
        portfolio_context,
        memory_context,
    )
