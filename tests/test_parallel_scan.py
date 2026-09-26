## Verify that scanning many option chains at once stays correct as well as fast.
##
## Overlapping the broker requests is only safe if the scan still behaves like the
## sequential one it replaced: the same tickers in the same order, one bad ticker
## costing only itself, and a throttled request asked for again rather than dropped.

import time
import unittest
from unittest.mock import Mock, patch

import pandas as pd

from backend.strategy.cash_secured_put import CASH_SECURED_PUT
from backend.strategy.engine.candidates import find_option_candidates
from backend.strategy.spec import ScanContext

TICKERS = ["AAPL", "MSFT", "NVDA", "AMZN", "META", "TSLA"]


## Build a scan context with stub clients; the chain scan itself is patched per test.
def scan_context():
    return ScanContext(
        available_capital=50_000,
        latest_prices={ticker: {"price": 100.0} for ticker in TICKERS},
        portfolio_context={},
        stock_data_client=Mock(),
        option_data_client=Mock(),
    )


## Return a one-row candidate frame tagged with its ticker.
def candidate_frame(ticker_symbol):
    return pd.DataFrame([{"tickerSymbol": ticker_symbol, "score": 1.0}])


class ParallelScanTests(unittest.TestCase):
    ## Whichever response lands first, the candidates come back in the order the tickers were given.
    def test_results_keep_ticker_order_regardless_of_completion_order(self):
        # The last ticker answers fastest, so completion order is the reverse of input order.
        def scan(_strategy, ticker_symbol, *_args, **_kwargs):
            time.sleep(0.01 * (len(TICKERS) - TICKERS.index(ticker_symbol)))
            return candidate_frame(ticker_symbol)

        with patch("backend.strategy.engine.candidates.scan_ticker_option_chain", scan):
            result = find_option_candidates(CASH_SECURED_PUT, TICKERS, scan_context())

        self.assertEqual(list(result.candidates["tickerSymbol"]), TICKERS)
        self.assertEqual(result.errors, ())

    ## The requests genuinely overlap, which is the whole point of the change.
    def test_chains_are_fetched_concurrently(self):
        def scan(_strategy, ticker_symbol, *_args, **_kwargs):
            time.sleep(0.05)
            return candidate_frame(ticker_symbol)

        started_at = time.monotonic()
        with patch("backend.strategy.engine.candidates.scan_ticker_option_chain", scan):
            find_option_candidates(CASH_SECURED_PUT, TICKERS, scan_context())
        elapsed = time.monotonic() - started_at

        # Six 50ms scans take 300ms in sequence; overlapping them must beat that clearly.
        self.assertLess(elapsed, 0.20)

    ## One unreadable chain costs only its own ticker, and is reported rather than hidden.
    def test_one_failing_ticker_does_not_end_the_scan(self):
        def scan(_strategy, ticker_symbol, *_args, **_kwargs):
            if ticker_symbol == "NVDA":
                raise ValueError("chain unavailable")
            return candidate_frame(ticker_symbol)

        with patch("backend.strategy.engine.candidates.scan_ticker_option_chain", scan):
            result = find_option_candidates(CASH_SECURED_PUT, TICKERS, scan_context())

        self.assertEqual(
            list(result.candidates["tickerSymbol"]),
            [ticker for ticker in TICKERS if ticker != "NVDA"],
        )
        self.assertEqual(result.errors, ("NVDA:ValueError",))

    ## A throttled request is asked for again, because dropping it would narrow the choice silently.
    @patch("backend.strategy.engine.candidates.time.sleep")
    def test_a_rate_limited_ticker_is_retried_once(self, sleep):
        attempts = []

        def scan(_strategy, ticker_symbol, *_args, **_kwargs):
            attempts.append(ticker_symbol)
            if ticker_symbol == "MSFT" and attempts.count("MSFT") == 1:
                raise RuntimeError("429 too many requests")
            return candidate_frame(ticker_symbol)

        with patch("backend.strategy.engine.candidates.scan_ticker_option_chain", scan):
            result = find_option_candidates(CASH_SECURED_PUT, TICKERS, scan_context())

        self.assertEqual(attempts.count("MSFT"), 2)
        self.assertIn("MSFT", list(result.candidates["tickerSymbol"]))
        self.assertEqual(result.errors, ())
        sleep.assert_called_once()

    ## A ticker that keeps failing for an ordinary reason is not retried.
    @patch("backend.strategy.engine.candidates.time.sleep")
    def test_an_ordinary_failure_is_not_retried(self, sleep):
        attempts = []

        def scan(_strategy, ticker_symbol, *_args, **_kwargs):
            attempts.append(ticker_symbol)
            raise ValueError("bad symbol")

        with patch("backend.strategy.engine.candidates.scan_ticker_option_chain", scan):
            result = find_option_candidates(CASH_SECURED_PUT, ["AAPL"], scan_context())

        self.assertEqual(attempts, ["AAPL"])
        self.assertEqual(result.errors, ("AAPL:ValueError",))
        sleep.assert_not_called()

    ## Only each ticker's best few contracts continue, so one liquid chain cannot crowd out the rest.
    def test_each_ticker_contributes_only_its_best_contracts(self):
        def scan(_strategy, ticker_symbol, *_args, **_kwargs):
            return pd.DataFrame([
                {"tickerSymbol": ticker_symbol, "score": float(10 - index)}
                for index in range(6)
            ])

        with patch("backend.strategy.engine.candidates.scan_ticker_option_chain", scan):
            result = find_option_candidates(CASH_SECURED_PUT, ["AAPL", "MSFT"], scan_context())

        counts = result.candidates["tickerSymbol"].value_counts()
        self.assertEqual(counts["AAPL"], 3)
        self.assertEqual(counts["MSFT"], 3)


if __name__ == "__main__":
    unittest.main()
