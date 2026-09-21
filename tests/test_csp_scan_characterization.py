## Pin the exact output of the CSP scan so refactoring cannot change it silently.
##
## The candidate engine had no test coverage, and the review prompt is a long
## tuned instruction block where a dropped paragraph would quietly change what
## the model does. Both are captured here as golden files recorded from the
## behavior that existed before the strategy-engine refactor. Regenerate them
## only on a deliberate behavior change: HELIOS_WRITE_GOLDEN=1 python -m unittest ...

import json
import os
import unittest
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from backend.strategy.cash_secured_put import CASH_SECURED_PUT
from backend.strategy.engine.candidates import scan_ticker_option_chain
from backend.strategy.review_prompt import build_review_prompt

GOLDEN_DIR = Path(__file__).parent / "golden"
WRITE_GOLDEN = os.getenv("HELIOS_WRITE_GOLDEN") == "1"

TICKER = "AAPL"
CURRENT_PRICE = 190.0
AVAILABLE_CAPITAL = 50_000.0
DAYS_TO_EXPIRATION = 35

# Strategy thresholds the fixture is built to exercise, mirroring backend/config.py.
MIN_DTE, MAX_DTE = 30, 45
TARGET_DELTA, DELTA_TOLERANCE = -0.25, 0.05
MAX_SPREAD, MIN_QUOTE_SIZE = 0.50, 1
MIN_IV_PERCENT, MAX_IV_PERCENT = 20, 80
MIN_ROC_PERCENT = 0.50


## Return the fixture expiration in both formats the scan depends on.
## Keeping it a fixed number of days out makes DTE constant, so only the date text varies between runs.
def expiration_strings():
    expiration = date.today() + timedelta(days=DAYS_TO_EXPIRATION)
    return expiration.strftime("%Y-%m-%d"), expiration.strftime("%y%m%d")


## Replace the only run-dependent values so golden files stay stable across days.
## Every number in the fixture is fixed; only the expiration date text moves.
def normalize(text):
    expiration_iso, expiration_occ = expiration_strings()
    return text.replace(expiration_iso, "<EXP>").replace(expiration_occ, "<EXPOCC>")


## Build one Alpaca-shaped option snapshot.
## A missing quote is represented by passing bid=None, which the scan must skip entirely.
def snapshot(bid, ask, delta, implied_volatility, bid_size=5, ask_size=5):
    if bid is None:
        return SimpleNamespace(latest_quote=None, greeks=None, implied_volatility=None)
    return SimpleNamespace(
        latest_quote=SimpleNamespace(
            bid_price=bid,
            ask_price=ask,
            bid_size=bid_size,
            ask_size=ask_size,
        ),
        greeks=SimpleNamespace(delta=delta),
        implied_volatility=implied_volatility,
    )


## Build an option chain where each contract fails exactly one hard filter, plus two that pass.
## This exercises every rule in the pipeline and fixes the ranking order between the survivors.
def option_chain():
    _, expiration_occ = expiration_strings()

    def symbol(strike):
        return f"{TICKER}{expiration_occ}P{int(strike * 1000):08d}"

    return {
        # passes everything; sits exactly on target delta
        symbol(180): snapshot(3.00, 3.20, -0.25, 0.30, bid_size=10, ask_size=10),
        # passes everything; ranks lower than the 180 strike
        symbol(175): snapshot(2.00, 2.10, -0.22, 0.25),
        # spread 0.80 exceeds the 0.50 maximum
        symbol(185): snapshot(4.00, 4.80, -0.28, 0.35),
        # delta -0.12 sits outside the target band
        symbol(165): snapshot(1.00, 1.10, -0.12, 0.28),
        # implied volatility 12% is below the 20% floor
        symbol(178): snapshot(2.50, 2.60, -0.24, 0.12),
        # return on cash 0.03% is below the 0.50% floor
        symbol(170): snapshot(0.05, 0.10, -0.23, 0.30),
        # requires $60,000 of collateral, above the available capital
        symbol(600): snapshot(12.00, 12.30, -0.26, 0.30),
        # no quote at all
        symbol(172): snapshot(None, None, None, None),
    }


## Run the CSP candidate scan against the fixture chain.
## This is the single call site that moves when the scan is refactored behind a strategy spec.
def run_scan(option_data_client=None):
    if option_data_client is None:
        option_data_client = Mock()
        option_data_client.get_option_chain.return_value = option_chain()

    return scan_ticker_option_chain(
        CASH_SECURED_PUT,
        TICKER,
        AVAILABLE_CAPITAL,
        current_stock_price=CURRENT_PRICE,
        stock_data_client=Mock(),
        option_data_client=option_data_client,
    )


## Build the CSP review prompt for the surviving candidates.
## This is the single call site that moves when the prompt is owned by the strategy.
def run_prompt(candidates):
    return build_review_prompt(
        CASH_SECURED_PUT,
        candidates,
        STRATEGY_RULES_FIXTURE,
        market_context=MARKET_CONTEXT_FIXTURE,
        portfolio_context=PORTFOLIO_CONTEXT_FIXTURE,
        memory_context=MEMORY_CONTEXT_FIXTURE,
    )


STRATEGY_RULES_FIXTURE = {
    "strategy": "cash-secured put",
    "approved_tickers": ["AAPL", "MSFT"],
    "target_delta": TARGET_DELTA,
    "delta_tolerance": DELTA_TOLERANCE,
    "min_dte": MIN_DTE,
    "max_dte": MAX_DTE,
    "max_spread": MAX_SPREAD,
    "min_iv_percent": MIN_IV_PERCENT,
    "max_iv_percent": MAX_IV_PERCENT,
    "min_roc_percent": MIN_ROC_PERCENT,
    "max_csp_capital_percent": 0.70,
    "max_open_positions": 5,
    "minimum_pattern_sample_size": 11,
}

MARKET_CONTEXT_FIXTURE = {
    "trends": [{"ticker": "AAPL", "1d": 0.4, "5d": 1.2, "2w": 2.0, "1m": 3.1, "ytd": 12.0}],
    "news_and_earnings": [{
        "headline": "Apple reports quarterly results",
        "summary": "Revenue rose modestly against guidance.",
        "source": "Reuters",
        "source_quality": "high",
        "created_at": "2026-01-02T00:00:00Z",
        "symbols": ["AAPL"],
        "tags": ["earnings"],
        "why_it_matters": "Earnings can move the underlying during the option's life.",
        "category": "earnings",
    }],
    "candidate_tickers": ["AAPL"],
}

PORTFOLIO_CONTEXT_FIXTURE = {
    "capital": {"total_capital": 100000.0, "committed_capital": 18000.0},
    "open_csp_positions": [{
        "ticker_symbol": "MSFT",
        "contract_symbol": "MSFT261218P00400000",
        "strike": 400.0,
        "quantity": 1,
        "premium_received": 250.0,
        "cash_required": 40000.0,
    }],
    "position_source": "alpaca",
}

MEMORY_CONTEXT_FIXTURE = {
    "relevant_episodes": [],
    "outcome_patterns": {"patterns": [], "recent_lessons": [], "minimum_sample_size": 11},
    "recent_outcome_snapshots": [],
    "user_profile": None,
    "memory_policy": {},
}


## Compare one captured artifact against its golden file, or record it when explicitly regenerating.
## Recording is opt-in so a refactor can never quietly rewrite the baseline it is being checked against.
def assert_matches_golden(test, name, actual_text):
    GOLDEN_DIR.mkdir(exist_ok=True)
    golden_path = GOLDEN_DIR / name
    normalized = normalize(actual_text)

    if WRITE_GOLDEN:
        golden_path.write_text(normalized)
        return

    test.assertTrue(
        golden_path.exists(),
        f"Missing golden {name}. Regenerate with HELIOS_WRITE_GOLDEN=1.",
    )
    test.assertEqual(normalized, golden_path.read_text())


class CspScanCharacterizationTests(unittest.TestCase):
    ## Only the contracts that satisfy every hard rule may survive the scan.
    def test_hard_filters_keep_exactly_the_qualifying_contracts(self):
        candidates = run_scan()
        _, expiration_occ = expiration_strings()

        self.assertEqual(
            list(candidates["contractSymbol"]),
            [
                f"{TICKER}{expiration_occ}P00180000",
                f"{TICKER}{expiration_occ}P00175000",
            ],
        )

    ## The option chain must be requested for puts inside the configured expiration window.
    def test_chain_is_requested_for_puts_only(self):
        option_data_client = Mock()
        option_data_client.get_option_chain.return_value = option_chain()
        run_scan(option_data_client)

        request = option_data_client.get_option_chain.call_args.args[0]
        self.assertEqual(request.underlying_symbol, TICKER)
        self.assertEqual(str(request.type).lower().split(".")[-1], "put")

    ## Every derived column and the ranking order must survive refactoring unchanged.
    def test_candidate_rows_match_golden(self):
        candidates = run_scan()
        rows = json.loads(candidates.to_json(orient="records"))
        assert_matches_golden(
            self,
            "csp_candidates.json",
            json.dumps(rows, indent=2, sort_keys=True),
        )

    ## The tuned review prompt must survive refactoring character for character.
    def test_review_prompt_matches_golden(self):
        prompt = run_prompt(run_scan())
        assert_matches_golden(self, "csp_review_prompt.txt", prompt)


if __name__ == "__main__":
    unittest.main()
