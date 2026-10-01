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
    fetch_ticker_earnings,
    refresh_earnings_calendar,
    summarize_reports,
)

TODAY = date(2026, 10, 1)

REPORTS = [
    {"date": "2026-04-28", "epsActual": 1.90, "epsEstimate": 1.85, "hour": "amc"},
    {"date": "2026-07-29", "epsActual": 2.18, "epsEstimate": 2.10, "hour": "amc"},
    {"date": "2026-10-28", "epsActual": None, "epsEstimate": 2.31, "hour": "amc"},
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
    ## The latest filed report and the next due one are read from the same list.
    def test_last_filed_and_next_due_are_separated(self):
        summary = summarize_reports("AAPL", REPORTS, today=TODAY)

        self.assertEqual(summary["last_reported_on"], "2026-07-29")
        self.assertEqual(summary["last_eps_actual"], 2.18)
        self.assertEqual(summary["last_eps_estimate"], 2.10)
        self.assertEqual(summary["next_report_on"], "2026-10-28")
        self.assertEqual(summary["next_eps_estimate"], 2.31)

    ## Beating or missing the estimate is stated, since that is the point of showing both.
    def test_the_surprise_is_calculated(self):
        self.assertAlmostEqual(summarize_reports("AAPL", REPORTS, today=TODAY)["last_eps_surprise"], 0.08)

    ## The countdown is what makes a row useful beside a contract with a known expiry.
    def test_days_until_the_next_report(self):
        self.assertEqual(summarize_reports("AAPL", REPORTS, today=TODAY)["days_until_next_report"], 27)

    ## A date that has passed with no figure is still pending, not a result nobody has.
    def test_a_passed_date_without_a_figure_is_not_treated_as_reported(self):
        stale = [{"date": "2026-09-20", "epsActual": None, "epsEstimate": 1.4}]

        summary = summarize_reports("NKE", stale, today=TODAY)

        self.assertIsNone(summary["last_reported_on"])
        # It is in the past, so it is not advertised as upcoming either.
        self.assertIsNone(summary["next_report_on"])

    ## A company with nothing on file reports blanks rather than inventing a schedule.
    def test_a_company_with_no_reports_returns_empty_fields(self):
        summary = summarize_reports("ZZZZ", [], today=TODAY)

        self.assertIsNone(summary["last_reported_on"])
        self.assertIsNone(summary["next_report_on"])
        self.assertIsNone(summary["days_until_next_report"])


class EarningsFetchTests(unittest.TestCase):
    ## The lookup asks for one symbol across a window that holds its last and next report.
    @patch("backend.market.earnings.FINNHUB_API_KEY", "test-key")
    def test_the_request_is_scoped_to_one_symbol_and_window(self):
        session = Mock()
        session.get.return_value = Mock(json=lambda: {"earningsCalendar": REPORTS}, raise_for_status=lambda: None)

        reports = fetch_ticker_earnings("AAPL", session=session)

        params = session.get.call_args.kwargs["params"]
        self.assertEqual(params["symbol"], "AAPL")
        self.assertLess(params["from"], params["to"])
        self.assertEqual([r["date"] for r in reports], ["2026-04-28", "2026-07-29", "2026-10-28"])

    ## Without a key the refresh says so rather than failing company by company.
    @patch("backend.market.earnings.FINNHUB_API_KEY", "")
    def test_refresh_reports_a_missing_key(self):
        result = refresh_earnings_calendar()

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "finnhub_not_configured")

    ## One unreadable company is recorded and skipped, leaving the rest of the table fresh.
    @patch("backend.market.earnings.put_item")
    @patch("backend.market.earnings.fetch_ticker_earnings")
    @patch("backend.market.earnings.earnings_tickers", return_value=["AAPL", "BROKEN", "MSFT"])
    @patch("backend.market.earnings.FINNHUB_API_KEY", "test-key")
    def test_one_failure_does_not_stop_the_refresh(self, _tickers, fetch, put_item):
        fetch.side_effect = lambda ticker, session=None: (_ for _ in ()).throw(RuntimeError("boom")) if ticker == "BROKEN" else REPORTS

        result = refresh_earnings_calendar()

        self.assertEqual(result["refreshed"], 2)
        self.assertEqual(result["failed"], ["BROKEN"])
        self.assertEqual(put_item.call_count, 2)


if __name__ == "__main__":
    unittest.main()
