## Track when each approved company last reported and when it reports next.
##
## HELIOS sells contracts that run thirty to forty-five days, which almost always spans
## a quarterly report, so "when does this company report" is context the user needs while
## reading a recommendation. News could only ever say whether a journalist wrote about
## earnings recently; this says what the calendar actually holds.
##
## Exchange-traded funds are absent on purpose. A fund is a basket of companies rather
## than a company, so it has no report to give, and listing one would mean a permanently
## empty row pretending to be missing data.
##
## The calendar changes about once a quarter per company, so it is fetched on a schedule
## and served from storage. Every page view hitting the provider would spend a rate limit
## on an answer that had not changed since the morning.

import logging
import time
from datetime import date, datetime, timedelta

from backend.config import (
    APPROVED_TICKERS,
    FINNHUB_MAX_CALLS_PER_MINUTE,
    EARNINGS_LOOKAHEAD_DAYS,
    EARNINGS_LOOKBACK_DAYS,
    ETF_TICKERS,
    FINNHUB_API_KEY,
    FINNHUB_BASE_URL,
    FINNHUB_TIMEOUT_SECONDS,
)
from backend.memory.dynamodb_store import get_item, put_item, query_items, utc_now_text
from backend.numbers import number_or_none

logger = logging.getLogger(__name__)

EARNINGS_PK = "SYSTEM#EARNINGS"
EARNINGS_SORT_KEY_PREFIX = "TICKER"


## Return the approved tickers that actually report earnings.
## One definition, so the view, the refresh job, and any later rule all cover the same names.
def earnings_tickers():
    return [ticker for ticker in APPROVED_TICKERS if ticker not in ETF_TICKERS]


## Build the storage key holding one company's earnings record.
def earnings_sort_key(ticker_symbol):
    return f"{EARNINGS_SORT_KEY_PREFIX}#{ticker_symbol}"


## Hold the pace under the provider's per-minute allowance.
##
## Every request waits out whatever is left of its own slot, so a burst can never form.
## This is simpler than reacting to a refusal after the fact, and the refresh is a
## background job where a minute and a half costs nothing.
def _wait_for_slot(last_call_at):
    gap = 60.0 / FINNHUB_MAX_CALLS_PER_MINUTE
    waited = time.monotonic() - last_call_at

    if waited < gap:
        time.sleep(gap - waited)

    return time.monotonic()


## Call one Finnhub endpoint and return its decoded body.
def _get(path, params, session=None):
    import requests

    response = (session or requests).get(
        f"{FINNHUB_BASE_URL}/{path}",
        params={**params, "token": FINNHUB_API_KEY},
        timeout=FINNHUB_TIMEOUT_SECONDS,
    )
    response.raise_for_status()

    return response.json()


## Fetch the reports a company still has ahead of it, soonest first.
##
## The calendar carries scheduled dates and the consensus estimate for them. In practice
## it reaches only about a month into the past, which is why the reports a company has
## already filed are fetched separately rather than read out of this same list.
def fetch_upcoming_reports(ticker_symbol, session=None):
    today = date.today()
    body = _get("calendar/earnings", {
        "from": today.isoformat(),
        "to": (today + timedelta(days=EARNINGS_LOOKAHEAD_DAYS)).isoformat(),
        "symbol": ticker_symbol,
    }, session)
    reports = (body or {}).get("earningsCalendar") or []

    return sorted(reports, key=lambda report: str(report.get("date") or ""))


## Fetch the quarters a company has already reported, oldest first.
##
## This is the endpoint that actually carries filed results, going back four quarters on
## the free tier, which is three more than the view needs. Its fields are named
## differently from the calendar's, so both namings are read through one normalizer.
def fetch_reported_results(ticker_symbol, session=None):
    results = _get("stock/earnings", {"symbol": ticker_symbol}, session) or []

    return sorted(results, key=lambda result: str(_report_date(result) or ""))


## Read a report's date whichever endpoint it came from.
##
## The two endpoints mean different things by it. A scheduled report carries the day it
## will be announced, while a filed result carries the end of the quarter it covers, which
## is why every company's filed date lands on the same few quarter boundaries. The announced
## date is not available for older quarters, so the period is reported as the period it is.
def _report_date(report):
    return report.get("date") or report.get("period")


## Read a report's filed figure whichever endpoint it came from.
def _report_actual(report):
    return number_or_none(report.get("epsActual") if "epsActual" in report else report.get("actual"))


## Read a report's expected figure whichever endpoint it came from.
def _report_estimate(report):
    return number_or_none(report.get("epsEstimate") if "epsEstimate" in report else report.get("estimate"))


## Split one company's reports into the last one filed and the next one due.
##
## A report counts as filed only when the provider carries an actual figure for it. A
## date that has passed without one usually means the provider has not caught up yet,
## so it stays in the upcoming half rather than being reported as a result nobody has.
def summarize_reports(ticker_symbol, upcoming_reports, reported_results=(), today=None):
    today = (today or date.today()).isoformat()
    reported = [r for r in reported_results if _report_actual(r) is not None]
    upcoming = [
        r for r in upcoming_reports
        if _report_actual(r) is None and str(_report_date(r) or "") >= today
    ]
    last = reported[-1] if reported else None
    following = upcoming[0] if upcoming else None

    actual = _report_actual(last or {})
    estimate = _report_estimate(last or {})

    return {
        "ticker_symbol": ticker_symbol,
        "last_period_end": _report_date(last or {}),
        "last_eps_actual": actual,
        "last_eps_estimate": estimate,
        # Stated rather than left to the reader, since beating or missing is the point of the row.
        "last_eps_surprise": (
            round(actual - estimate, 4) if actual is not None and estimate is not None else None
        ),
        "next_report_on": _report_date(following or {}),
        "next_eps_estimate": _report_estimate(following or {}),
        # Finnhub marks whether a report lands before the open or after the close.
        "next_report_timing": (following or {}).get("hour"),
        "days_until_next_report": _days_until(_report_date(following or {}), today),
    }


## Count days from today to a report date, or None when there is no date to count to.
## The number is what makes a row useful next to a contract that expires in thirty-eight days.
def _days_until(report_date, today):
    if not report_date:
        return None

    try:
        days = (datetime.fromisoformat(str(report_date)).date() - datetime.fromisoformat(today).date()).days
    except (TypeError, ValueError):
        return None

    return days if days >= 0 else None


## Refresh every reporting company's record and store what came back.
##
## One company failing is recorded and skipped rather than ending the refresh, because a
## single unreadable symbol should not leave the whole table stale.
def refresh_earnings_calendar():
    if not FINNHUB_API_KEY:
        return {"ok": False, "error": "finnhub_not_configured"}

    import requests

    session = requests.Session()
    refreshed, failed = 0, []
    last_call_at = 0.0

    for ticker_symbol in earnings_tickers():
        try:
            last_call_at = _wait_for_slot(last_call_at)
            upcoming = fetch_upcoming_reports(ticker_symbol, session)
            last_call_at = _wait_for_slot(last_call_at)
            summary = summarize_reports(
                ticker_symbol,
                upcoming,
                fetch_reported_results(ticker_symbol, session),
            )
        except Exception as error:
            logger.warning("Earnings lookup failed for %s: %s", ticker_symbol, type(error).__name__)
            failed.append(ticker_symbol)
            continue

        put_item({
            "pk": EARNINGS_PK,
            "sk": earnings_sort_key(ticker_symbol),
            "item_type": "earnings_calendar",
            "refreshed_at": utc_now_text(),
            **summary,
        })
        refreshed += 1

    logger.info("Earnings calendar refreshed for %s companies (%s failed)", refreshed, len(failed))

    return {"ok": not failed, "refreshed": refreshed, "failed": failed}


## Return the stored earnings table, soonest report first.
##
## A company with no known next date sorts last rather than first, so an unknown never
## takes the top of a list the user reads as "what is coming up".
def get_earnings_calendar():
    rows = query_items(EARNINGS_PK, f"{EARNINGS_SORT_KEY_PREFIX}#", limit=len(APPROVED_TICKERS))
    today = date.today().isoformat()

    for row in rows:
        # Counted now rather than trusted from the last refresh, since a stored countdown is
        # wrong by however many days have passed since. A date already gone leaves no count
        # at all, because the stored schedule is behind rather than the report being due.
        row["days_until_next_report"] = _days_until(row.get("next_report_on"), today)

    return sorted(rows, key=lambda row: (row.get("next_report_on") is None, row.get("next_report_on") or ""))


## Return just the next report date and countdown for every company, keyed by ticker.
## Views that only need to say "reports in six days" should not carry the whole table to do it.
def next_report_by_ticker():
    return {
        row["ticker_symbol"]: {
            "next_report_on": row.get("next_report_on"),
            "days_until_next_report": row.get("days_until_next_report"),
        }
        for row in get_earnings_calendar()
        if row.get("ticker_symbol")
    }


## Return one company's stored earnings record, or None when it has never been fetched.
## Candidate cards use this to say how close a report is without reloading the whole table.
def get_ticker_earnings(ticker_symbol):
    return get_item(EARNINGS_PK, earnings_sort_key(ticker_symbol))
