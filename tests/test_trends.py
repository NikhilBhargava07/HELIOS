## Verify that human-readable trend labels map to trading-session windows.

import unittest
from types import SimpleNamespace

from backend.market.trends import TREND_PERIODS, build_price_trend


class TrendWindowTests(unittest.TestCase):
    ## Keep two-week and one-month labels aligned with market sessions, not calendar days.
    def test_period_constants_use_trading_sessions(self):
        self.assertEqual(TREND_PERIODS["2w"], 10)
        self.assertEqual(TREND_PERIODS["1m"], 21)

    ## Select the close exactly ten sessions before the latest bar for a two-week change.
    def test_two_week_trend_uses_ten_intervals(self):
        bars = [SimpleNamespace(close=float(value)) for value in range(100, 112)]

        result = build_price_trend("AAPL", "2w", bars)

        self.assertEqual(result["start_price"], 101.0)
        self.assertEqual(result["end_price"], 111.0)
        self.assertEqual(result["dollar_change"], 10.0)


if __name__ == "__main__":
    unittest.main()
