from ai_review import *
from csp_candidates import *
import pandas as pd

APPROVED_TICKERS = ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "SPY", "QQQ", "CSCO", "TSLA", "META"]  # Approved ticker list
MIN_DTE = 30  # Minimum days to expiration for options to consider
MAX_DTE = 45  # Maximum days to expiration for options to consider
TARGET_DELTA = -0.25  # Target delta for cash-secured puts
DELTA_TOLERANCE = 0.05  # Allows deltas from -0.30 to -0.20
MAX_SPREAD = 0.50  # Maximum allowed bid/ask spread
MIN_QUOTE_SIZE = 1  # Minimum bid and ask size available at the current quote
MIN_IV_PERCENT = 20  # Minimum implied volatility percentage
MAX_IV_PERCENT = 80  # Avoid extremely high IV contracts for now
MIN_ROC_PERCENT = 0.50  # Minimum return on cash percentage
TOTAL_CAPITAL = 100000  # Simulated account size
MAX_CSP_CAPITAL_PERCENT = 0.70  # Use at most 70% of account for CSP collateral
CURRENT_CSP_CAPITAL_COMMITTED = 0  # Update later from open CSP positions
MAX_OPEN_POSITIONS = 5  # Abstract suggests 3-5 open positions max
CURRENT_OPEN_POSITIONS = 0  # Update later from a position tracker
CANDIDATES_PER_TICKER = 1  # Keep each ticker's best candidate for cross-ticker review
MAX_RECOMMENDATIONS = 3  # Show up to this many filtered CSP candidates

STRATEGY_RULES = {
    "strategy": "cash-secured put",
    "approved_tickers": APPROVED_TICKERS,
    "target_delta": TARGET_DELTA,
    "delta_tolerance": DELTA_TOLERANCE,
    "min_dte": MIN_DTE,
    "max_dte": MAX_DTE,
    "max_spread": MAX_SPREAD,
    "min_iv_percent": MIN_IV_PERCENT,
    "max_iv_percent": MAX_IV_PERCENT,
    "min_roc_percent": MIN_ROC_PERCENT,
    "max_csp_capital_percent": MAX_CSP_CAPITAL_PERCENT,
    "max_open_positions": MAX_OPEN_POSITIONS,
}

def is_approved_ticker(ticker_symbol, approved_tickers):
    return ticker_symbol in approved_tickers


def can_open_new_position(current_open_positions, max_open_positions):
    return current_open_positions < max_open_positions


def calculate_available_csp_capital(total_capital, max_csp_capital_percent, current_csp_capital_committed):
    max_csp_capital = total_capital * max_csp_capital_percent
    available_csp_capital = max_csp_capital - current_csp_capital_committed

    return max(0, available_csp_capital)


def print_recommendations(candidates):
    for recommendation_number, candidate in enumerate(candidates.itertuples(), start=1):
        print(
            f"{recommendation_number}. Sell 1 {candidate.tickerSymbol} ${candidate.strike:.2f} put "
            f"expiring {candidate.expiration} ({candidate.DTE} DTE)"
        )
        print(
            f"   Price: ${candidate.currentStockPrice:.2f} | Delta: {candidate.delta:.3f} | "
            f"IV: {candidate.ivPercent:.2f}% | Spread: ${candidate.spread:.2f}"
        )
        print(
            f"   Premium: ${candidate.premiumIfSoldAtBid:.2f} | Cash required: "
            f"${candidate.cashRequired:.2f} | Breakeven: ${candidate.breakevenPrice:.2f} | "
            f"ROC: {candidate.returnOnCashPercent:.2f}%"
        )
        print(
            f"   Why: close to {TARGET_DELTA} delta, tight spread, decent IV, "
            "and breakeven is below current price."
        )
        print()


def print_ai_review(review):
    print("Agent review:")
    print(f"Decision: {review['decision']}")

    if review["selected_contract"]:
        print(f"Selected contract: {review['selected_contract']}")

    print(f"Summary: {review['summary']}")
    print(f"Risk note: {review['risk_note']}")
    print()


def get_recommendation_results(
    current_open_positions=CURRENT_OPEN_POSITIONS,
    current_csp_capital_committed=CURRENT_CSP_CAPITAL_COMMITTED,
):
    if not can_open_new_position(current_open_positions, MAX_OPEN_POSITIONS):
        return {
            "candidates": pd.DataFrame(),
            "review": {
                "decision": "reject_all",
                "selected_contract": None,
                "summary": f"Max open positions reached ({MAX_OPEN_POSITIONS}).",
                "risk_note": "Position limits prevent overcommitting the account.",
            },
        }

    available_csp_capital = calculate_available_csp_capital(
        TOTAL_CAPITAL,
        MAX_CSP_CAPITAL_PERCENT,
        current_csp_capital_committed,
    )

    if available_csp_capital <= 0:
        return {
            "candidates": pd.DataFrame(),
            "review": {
                "decision": "reject_all",
                "selected_contract": None,
                "summary": "No CSP capital available under current allocation rules.",
                "risk_note": "Capital allocation rules keep the account from being overcommitted.",
            },
        }

    all_candidates = []

    for ticker_symbol in APPROVED_TICKERS:
        candidates = find_csp_candidates(
            ticker_symbol,
            MIN_DTE,
            MAX_DTE,
            TARGET_DELTA,
            DELTA_TOLERANCE,
            MAX_SPREAD,
            MIN_QUOTE_SIZE,
            MIN_IV_PERCENT,
            MAX_IV_PERCENT,
            MIN_ROC_PERCENT,
            available_csp_capital,
        )

        if not candidates.empty:
            all_candidates.append(candidates.head(CANDIDATES_PER_TICKER))

    if not all_candidates:
        return {
            "candidates": pd.DataFrame(),
            "review": {
                "decision": "reject_all",
                "selected_contract": None,
                "summary": "No CSP candidates found across approved tickers.",
                "risk_note": "The current filters may be too strict for today's market data.",
            },
        }

    combined_candidates = pd.concat(all_candidates, ignore_index=True)
    combined_candidates = combined_candidates.sort_values(by="score", ascending=False)
    top_candidates = combined_candidates.head(MAX_RECOMMENDATIONS)
    review = review_csp_candidates("approved ticker list", top_candidates, STRATEGY_RULES)

    return {
        "candidates": top_candidates,
        "review": review,
    }


def main():
    print(f"Scanning approved tickers: {', '.join(APPROVED_TICKERS)}\n")
    results = get_recommendation_results()
    top_candidates = results["candidates"]
    review = results["review"]

    if top_candidates.empty:
        print(review["summary"])
        print(review["risk_note"])
        return

    print("\nTop CSP candidates across approved tickers:\n")
    print_recommendations(top_candidates)
    print_ai_review(review)

if __name__ == "__main__":
    main()
