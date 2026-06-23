"""Command-line entry point for running a CSP recommendation scan."""

from backend.config import APPROVED_TICKERS, TARGET_DELTA
from backend.strategy.recommender import get_recommendation_results


def print_recommendations(candidates):
    """Print ranked CSP candidates in a beginner-readable terminal format."""
    for number, candidate in enumerate(candidates.itertuples(), start=1):
        print(
            f"{number}. Sell 1 {candidate.tickerSymbol} ${candidate.strike:.2f} put "
            f"expiring {candidate.expiration} ({candidate.DTE} DTE)"
        )
        print(
            f"   Price: ${candidate.currentStockPrice:.2f} | Delta: {candidate.delta:.3f} | "
            f"IV: {candidate.ivPercent:.2f}% | Spread: ${candidate.spread:.2f}"
        )
        print(
            f"   Premium: ${candidate.premiumIfSoldAtBid:.2f} | "
            f"Cash: ${candidate.cashRequired:.2f} | "
            f"Breakeven: ${candidate.breakevenPrice:.2f} | "
            f"ROC: {candidate.returnOnCashPercent:.2f}%"
        )
        print(
            f"   Why: close to {TARGET_DELTA} delta, tight spread, reasonable IV, "
            "and breakeven below the current price.\n"
        )


def print_ai_review(review):
    """Print the structured AI decision and risk explanation."""
    print(f"Agent review:\nDecision: {review['decision']}")
    if review["selected_contract"]:
        print(f"Selected contract: {review['selected_contract']}")
    print(f"Summary: {review['summary']}\nRisk note: {review['risk_note']}\n")


def main():
    """Run the recommendation pipeline from the terminal."""
    print(f"Scanning approved tickers: {', '.join(APPROVED_TICKERS)}\n")
    results = get_recommendation_results()
    if results["candidates"].empty:
        print(results["review"]["summary"])
        print(results["review"]["risk_note"])
        return
    print_recommendations(results["candidates"])
    print_ai_review(results["review"])


if __name__ == "__main__":
    main()
