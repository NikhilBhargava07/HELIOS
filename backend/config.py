## Central configuration for the CSP recommendation prototype.
##
## This module owns the approved universe, display names, portfolio limits, and
## hard screening thresholds. Keeping these values together makes strategy
## changes auditable and prevents route or broker modules from defining policy.

import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.5")
DYNAMODB_TABLE_NAME = os.getenv("DYNAMODB_TABLE_NAME", "helios-memory")
USER_ID = os.getenv("HELIOS_USER_ID", "default")

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

MIN_DTE = 30
MAX_DTE = 45
TARGET_DELTA = -0.25
DELTA_TOLERANCE = 0.05
MAX_SPREAD = 0.50
MIN_QUOTE_SIZE = 1
MIN_IV_PERCENT = 20
MAX_IV_PERCENT = 80
MIN_ROC_PERCENT = 0.50

TOTAL_CAPITAL = 100_000
MAX_CSP_CAPITAL_PERCENT = 0.70
MAX_OPEN_POSITIONS = 5
CANDIDATES_PER_TICKER = 3
MAX_RECOMMENDATIONS = 10

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
