from csp_candidates import *
from printing_details import *

TICKER_SYMBOL = "NVDA"  # Change this to the stock ticker you want to analyze
MIN_DTE = 30  # Minimum days to expiration for options to consider
MAX_DTE = 45  # Maximum days to expiration for options to consider
TARGET_DELTA = -0.25  # Target delta for cash-secured puts
DELTA_TOLERANCE = 0.05  # Allows deltas from -0.30 to -0.20
MAX_SPREAD = 0.50  # Maximum allowed bid/ask spread
MIN_QUOTE_SIZE = 1  # Minimum bid and ask size available at the current quote
MIN_IV_PERCENT = 20  # Minimum implied volatility percentage
MAX_IV_PERCENT = 80  # Avoid extremely high IV contracts for now
MIN_ROC_PERCENT = 0.50  # Minimum return on cash percentage
AVAILABLE_CAPITAL = 100000  # Simulated account size
MAX_RECOMMENDATIONS = 3  # Show up to this many filtered CSP candidates

def print_recommendations(candidates):
    for recommendation_number, candidate in enumerate(candidates.itertuples(), start=1):
        print(
            f"{recommendation_number}. Sell 1 {TICKER_SYMBOL} ${candidate.strike:.2f} put "
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

def main():
    print_stock_price(TICKER_SYMBOL)
    print(f"Finding CSP candidates for {TICKER_SYMBOL}...\n")
    candidates = find_csp_candidates(
        TICKER_SYMBOL,
        MIN_DTE,
        MAX_DTE,
        TARGET_DELTA,
        DELTA_TOLERANCE,
        MAX_SPREAD,
        MIN_QUOTE_SIZE,
        MIN_IV_PERCENT,
        MAX_IV_PERCENT,
        MIN_ROC_PERCENT,
        AVAILABLE_CAPITAL,
    )

    if candidates.empty:
        print("No CSP candidates found.")
    else:
        top_candidates = candidates.head(MAX_RECOMMENDATIONS)
        print_recommendations(top_candidates)

if __name__ == "__main__":
    main()
