from csp_candidates import *
from printing_details import *

TICKER_SYMBOL = "AMZN"  # Change this to the stock ticker you want to analyze
MIN_DTE = 30  # Minimum days to expiration for options to consider
MAX_DTE = 45  # Maximum days to expiration for options to consider
MIN_VOLUME = 10  # Minimum volume for options to consider
MIN_OPEN_INTEREST = 100  # Minimum open interest for options to consider

def main():
    print_stock_price(TICKER_SYMBOL)
    print(f"Finding CSP candidates for {TICKER_SYMBOL}...\n")
    candidates = find_csp_candidates(TICKER_SYMBOL, MIN_DTE, MAX_DTE, MIN_VOLUME, MIN_OPEN_INTEREST)

    if candidates.empty:
        print("No CSP candidates found.")
    else:
        print(candidates)

if __name__ == "__main__":
    main()
