## Central configuration for the CSP recommendation prototype.
##
## This module owns the approved universe, display names, portfolio limits, and
## hard screening thresholds. Keeping these values together makes strategy
## changes auditable and prevents route or broker modules from defining policy.

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# These values come from Lambda environment variables in AWS. Local development
# uses the defaults so the project does not depend on unrelated values in .env.
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.5")
OPENAI_TIMEOUT_SECONDS = float(os.getenv("OPENAI_TIMEOUT_SECONDS", "180"))
OPENAI_MAX_RETRIES = int(os.getenv("OPENAI_MAX_RETRIES", "2"))
OPENAI_REASONING_EFFORT = os.getenv("OPENAI_REASONING_EFFORT", "low")
OPENAI_CSP_MAX_OUTPUT_TOKENS = int(
    os.getenv("OPENAI_CSP_MAX_OUTPUT_TOKENS", "5000")
)
OPENAI_MARKET_TAKE_MAX_OUTPUT_TOKENS = int(
    os.getenv("OPENAI_MARKET_TAKE_MAX_OUTPUT_TOKENS", "3000")
)
OPENAI_OUTCOME_REVIEW_MAX_OUTPUT_TOKENS = int(
    os.getenv("OPENAI_OUTCOME_REVIEW_MAX_OUTPUT_TOKENS", "3000")
)
DYNAMODB_TABLE_NAME = os.getenv("DYNAMODB_TABLE_NAME", "helios-memory")

APPROVED_TICKERS = [
    "SPY", "QQQ", "IWM", "DIA", "XLF", "XLK", "XLV", "XLE", "XLY",
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "AVGO", "AMD",
    "COST", "JPM", "V", "MA", "HD", "WMT", "ORCL", "NFLX", "CSCO",
    "TSLA", "INTC", "MU", "QCOM", "CRM", "UBER", "DIS", "NKE",
    "SBUX", "KO", "PEP", "T", "VZ", "BAC", "C", "WFC", "PYPL",
    "SHOP", "RBLX", "SNAP", "PINS", "SOFI", "PLTR", "HOOD", "F",
    "GM", "CCL", "DAL", "AAL", "UAL",
]

COMPANY_NAMES = {
    "SPY": "SPDR S&P 500 ETF Trust", "QQQ": "Invesco QQQ Trust",
    "IWM": "iShares Russell 2000 ETF", "DIA": "SPDR Dow Jones Industrial Average ETF Trust",
    "XLF": "Financial Select Sector SPDR Fund", "XLK": "Technology Select Sector SPDR Fund",
    "XLV": "Health Care Select Sector SPDR Fund", "XLE": "Energy Select Sector SPDR Fund",
    "XLY": "Consumer Discretionary Select Sector SPDR Fund", "AAPL": "Apple",
    "MSFT": "Microsoft", "GOOGL": "Alphabet", "AMZN": "Amazon", "NVDA": "NVIDIA",
    "META": "Meta Platforms", "AVGO": "Broadcom", "AMD": "Advanced Micro Devices",
    "COST": "Costco Wholesale", "JPM": "JPMorgan Chase", "V": "Visa",
    "MA": "Mastercard", "HD": "Home Depot", "WMT": "Walmart", "ORCL": "Oracle",
    "NFLX": "Netflix", "CSCO": "Cisco", "TSLA": "Tesla", "INTC": "Intel",
    "MU": "Micron Technology", "QCOM": "Qualcomm", "CRM": "Salesforce",
    "UBER": "Uber Technologies", "DIS": "Walt Disney", "NKE": "Nike",
    "SBUX": "Starbucks", "KO": "Coca-Cola", "PEP": "PepsiCo", "T": "AT&T",
    "VZ": "Verizon", "BAC": "Bank of America", "C": "Citigroup",
    "WFC": "Wells Fargo", "PYPL": "PayPal", "SHOP": "Shopify", "RBLX": "Roblox",
    "SNAP": "Snap", "PINS": "Pinterest", "SOFI": "SoFi Technologies",
    "PLTR": "Palantir", "HOOD": "Robinhood Markets", "F": "Ford",
    "GM": "General Motors", "CCL": "Carnival", "DAL": "Delta Air Lines",
    "AAL": "American Airlines", "UAL": "United Airlines",
}

# Portfolio-wide limits. These hold no matter which strategy is trading, so they
# live here rather than inside any one strategy. A strategy's own thresholds, such
# as a cash-secured put's target delta, live with that strategy in backend/strategy/.
TOTAL_CAPITAL = 100_000
MAX_OPEN_POSITIONS = 5
CANDIDATES_PER_TICKER = 3
MAX_RECOMMENDATIONS = 10
MIN_PATTERN_SAMPLE_SIZE = 11
AI_JOB_TTL_SECONDS = 86_400
MAX_RECOMMENDATION_AGE_SECONDS = 900

# The share of the account each strategy may commit, keyed by strategy. Only
# strategies that consume buying power appear here; a covered call is secured by
# shares already owned, so it ties up no capital and needs no budget.
CAPITAL_BUDGETS = {
    "cash_secured_put": 0.70,
}
