import os


HIGH_ROC_WARNING_PERCENT = 2.00


def build_candidate_summary(candidate):
    return {
        "contract_symbol": candidate.contractSymbol,
        "expiration": candidate.expiration,
        "dte": int(candidate.DTE),
        "strike": float(candidate.strike),
        "current_stock_price": float(candidate.currentStockPrice),
        "delta": float(candidate.delta),
        "iv_percent": float(candidate.ivPercent),
        "spread": float(candidate.spread),
        "premium": float(candidate.premiumIfSoldAtBid),
        "cash_required": float(candidate.cashRequired),
        "breakeven_price": float(candidate.breakevenPrice),
        "return_on_cash_percent": float(candidate.returnOnCashPercent),
    }


def prepare_candidates_for_ai(candidates):
    return [
        build_candidate_summary(candidate)
        for candidate in candidates.itertuples()
    ]


def local_review_csp_candidates(ticker_symbol, candidates):
    """
    Temporary rule-based review until an LLM API key is configured.
    This keeps the ai_review structure usable before OpenAI integration.
    """
    if candidates.empty:
        return {
            "decision": "reject_all",
            "selected_contract": None,
            "summary": "No candidates passed the hard CSP filters.",
            "risk_note": "Try another approved ticker or loosen filters only after understanding the tradeoff.",
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

    return {
        "decision": "approve",
        "selected_contract": best_candidate["contractSymbol"],
        "summary": (
            f"The top {ticker_symbol} CSP candidate has the best current balance of "
            "target delta, premium, spread, and breakeven among the filtered choices."
        ),
        "risk_note": " ".join(risk_notes),
    }


def review_csp_candidates(ticker_symbol, candidates, strategy_rules):
    """
    Future OpenAI integration point.

    The LLM should only review candidates that already passed hard rules.
    It can rank, explain, or veto, but it should never override filters.
    """
    if not os.getenv("OPENAI_API_KEY"):
        return local_review_csp_candidates(ticker_symbol, candidates)

    # TODO: Call OpenAI with structured JSON output.
    # Input should include:
    # - ticker_symbol
    # - prepare_candidates_for_ai(candidates)
    # - strategy_rules
    # - future user style profile / past trade outcomes
    return local_review_csp_candidates(ticker_symbol, candidates)
