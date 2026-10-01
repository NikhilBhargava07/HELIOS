## Verify the earnings calendar: what counts as reported, what is still due, and who is listed.
##
## The table is read while judging a trade that will span a quarterly report, so the two
## halves must not blur. A report counts as filed only when an actual figure exists, and a
## fund is never listed at all, because a basket of companies has no report of its own.

import unittest
from datetime import date
from unittest.mock import Mock, patch

from backend.config import ETF_TICKERS
from backend.market.earnings import (
    earnings_tickers,
    fetch_upcoming_reports,
    refresh_earnings_calendar,
    summarize_reports,
)

TODAY = date(2026, 10, 1)

# The calendar reaches only about a month back, so it carries what is still ahead.
UPCOMING = [
    {"date": "2026-10-28", "epsActual": None, "epsEstimate": 2.31, "hour": "amc"},
]

# Filed quarters come from a different endpoint, which names its fields differently.
RESULTS = [
    {"period": "2026-04-28", "actual": 1.90, "estimate": 1.85},
    {"period": "2026-07-29", "actual": 2.18, "estimate": 2.10},
]


class EarningsUniverseTests(unittest.TestCase):
    ## A fund holds companies rather than being one, so it has no report to list.
    def test_funds_are_not_listed(self):
        tickers = earnings_tickers()

        for fund in ETF_TICKERS:
            self.assertNotIn(fund, tickers)
        self.assertIn("AAPL", tickers)
        self.assertEqual(len(tickers), 47)


class EarningsSummaryTests(unittest.TestCase):
    ## The latest filed quarter and the next scheduled report are read from their own sources.
    def test_last_filed_and_next_due_are_separated(self):
        summary = summarize_reports("AAPL", UPCOMING, RESULTS, today=TODAY)

        self.assertEqual(summary["last_period_end"], "2026-07-29")
        self.assertEqual(summary["last_eps_actual"], 2.18)
        self.assertEqual(summary["last_eps_estimate"], 2.10)
        self.assertEqual(summary["next_report_on"], "2026-10-28")
        self.assertEqual(summary["next_eps_estimate"], 2.31)

    ## Beating or missing the estimate is stated, since that is the point of showing both.
    def test_the_surprise_is_calculated(self):
        self.assertAlmostEqual(summarize_reports("AAPL", UPCOMING, RESULTS, today=TODAY)["last_eps_surprise"], 0.08)

    ## The countdown is what makes a row useful beside a contract with a known expiry.
    def test_days_until_the_next_report(self):
        self.assertEqual(summarize_reports("AAPL", UPCOMING, RESULTS, today=TODAY)["days_until_next_report"], 27)

    ## The two endpoints name their fields differently, and both are read the same way.
    def test_both_field_namings_are_understood(self):
        calendar_style = summarize_reports("AAPL", UPCOMING, [
            {"date": "2026-07-29", "epsActual": 2.18, "epsEstimate": 2.10},
        ], today=TODAY)

        self.assertEqual(calendar_style["last_eps_actual"], 2.18)
        self.assertEqual(calendar_style["last_period_end"], "2026-07-29")

    ## A date that has passed with no figure is still pending, not a result nobody has.
    def test_a_passed_date_without_a_figure_is_not_treated_as_reported(self):
        stale = [{"date": "2026-09-20", "epsActual": None, "epsEstimate": 1.4}]

        summary = summarize_reports("NKE", stale, [], today=TODAY)

        self.assertIsNone(summary["last_period_end"])
        # It is in the past, so it is not advertised as upcoming either.
        self.assertIsNone(summary["next_report_on"])

    ## A company with nothing on file reports blanks rather than inventing a schedule.
    def test_a_company_with_no_reports_returns_empty_fields(self):
        summary = summarize_reports("ZZZZ", [], [], today=TODAY)

        self.assertIsNone(summary["last_period_end"])
        self.assertIsNone(summary["next_report_on"])
        self.assertIsNone(summary["days_until_next_report"])


class EarningsFetchTests(unittest.TestCase):
    ## The lookup asks for one symbol across a window that holds its last and next report.
    @patch("backend.market.earnings.FINNHUB_API_KEY", "test-key")
    def test_the_request_is_scoped_to_one_symbol_and_window(self):
        session = Mock()
        session.get.return_value = Mock(json=lambda: {"earningsCalendar": UPCOMING}, raise_for_status=lambda: None)

        reports = fetch_upcoming_reports("AAPL", session=session)

        params = session.get.call_args.kwargs["params"]
        self.assertEqual(params["symbol"], "AAPL")
        self.assertLess(params["from"], params["to"])
        self.assertEqual([r["date"] for r in reports], ["2026-10-28"])

    ## Without a key the refresh says so rather than failing company by company.
    @patch("backend.market.earnings.FINNHUB_API_KEY", "")
    def test_refresh_reports_a_missing_key(self):
        result = refresh_earnings_calendar()

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "finnhub_not_configured")

    ## The refresh paces itself, because the free tier allows far fewer calls than it can make.
    @patch("backend.market.earnings.time.sleep")
    @patch("backend.market.earnings.put_item")
    @patch("backend.market.earnings.fetch_reported_results", return_value=RESULTS)
    @patch("backend.market.earnings.fetch_upcoming_reports", return_value=UPCOMING)
    @patch("backend.market.earnings.earnings_tickers", return_value=["AAPL", "MSFT", "NVDA"])
    @patch("backend.market.earnings.FINNHUB_API_KEY", "test-key")
    def test_the_refresh_waits_between_calls(self, _tickers, _up, _res, _put, sleep):
        refresh_earnings_calendar()

        # Two endpoints per company is six calls, and the first has nothing to wait for.
        self.assertEqual(sleep.call_count, 5)
        self.assertGreater(sleep.call_args.args[0], 0)

    ## One unreadable company is recorded and skipped, leaving the rest of the table fresh.
    @patch("backend.market.earnings.time.sleep")
    @patch("backend.market.earnings.put_item")
    @patch("backend.market.earnings.fetch_reported_results", return_value=RESULTS)
    @patch("backend.market.earnings.fetch_upcoming_reports")
    @patch("backend.market.earnings.earnings_tickers", return_value=["AAPL", "BROKEN", "MSFT"])
    @patch("backend.market.earnings.FINNHUB_API_KEY", "test-key")
    def test_one_failure_does_not_stop_the_refresh(self, _tickers, fetch, _results, put_item, _sleep):
        fetch.side_effect = lambda ticker, session=None: (_ for _ in ()).throw(RuntimeError("boom")) if ticker == "BROKEN" else UPCOMING

        result = refresh_earnings_calendar()

        self.assertEqual(result["refreshed"], 2)
        self.assertEqual(result["failed"], ["BROKEN"])
        self.assertEqual(put_item.call_count, 2)


if __name__ == "__main__":
    unittest.main()
