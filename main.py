from csp_candidates import *
from printing_details import *

TICKER_SYMBOL = "NVDA"  # Change this to the stock ticker you want to analyze
APPROVED_TICKERS = ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "SPY", "QQQ"]
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
MAX_RECOMMENDATIONS = 3  # Show up to this many filtered CSP candidates

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
    if not is_approved_ticker(TICKER_SYMBOL, APPROVED_TICKERS):
        print(f"{TICKER_SYMBOL} is not on the approved ticker list.")
        print(f"Approved tickers: {', '.join(APPROVED_TICKERS)}")
        return

    if not can_open_new_position(CURRENT_OPEN_POSITIONS, MAX_OPEN_POSITIONS):
        print(f"No recommendation: max open positions reached ({MAX_OPEN_POSITIONS}).")
        return

    available_csp_capital = calculate_available_csp_capital(
        TOTAL_CAPITAL,
        MAX_CSP_CAPITAL_PERCENT,
        CURRENT_CSP_CAPITAL_COMMITTED,
    )

    if available_csp_capital <= 0:
        print("No recommendation: no CSP capital available under current allocation rules.")
        return

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
        available_csp_capital,
    )

    if candidates.empty:
        print("No CSP candidates found.")
    else:
        top_candidates = candidates.head(MAX_RECOMMENDATIONS)
        print_recommendations(top_candidates)

if __name__ == "__main__":
    main()
