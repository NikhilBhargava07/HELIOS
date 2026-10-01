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
from datetime import date, datetime, timedelta

from backend.config import (
    APPROVED_TICKERS,
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


## Fetch one company's reports inside the window, oldest first.
##
## Finnhub returns past and upcoming reports from the same endpoint, with an actual EPS
## present only once a company has reported, which is what separates the two.
def fetch_ticker_earnings(ticker_symbol, session=None):
    import requests

    today = date.today()
    response = (session or requests).get(
        f"{FINNHUB_BASE_URL}/calendar/earnings",
        params={
            "from": (today - timedelta(days=EARNINGS_LOOKBACK_DAYS)).isoformat(),
            "to": (today + timedelta(days=EARNINGS_LOOKAHEAD_DAYS)).isoformat(),
            "symbol": ticker_symbol,
            "token": FINNHUB_API_KEY,
        },
        timeout=FINNHUB_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    reports = (response.json() or {}).get("earningsCalendar") or []

    return sorted(reports, key=lambda report: str(report.get("date") or ""))


## Split one company's reports into the last one filed and the next one due.
##
## A report counts as filed only when the provider carries an actual figure for it. A
## date that has passed without one usually means the provider has not caught up yet,
## so it stays in the upcoming half rather than being reported as a result nobody has.
def summarize_reports(ticker_symbol, reports, today=None):
    today = (today or date.today()).isoformat()
    reported = [r for r in reports if number_or_none(r.get("epsActual")) is not None]
    upcoming = [
        r for r in reports
        if number_or_none(r.get("epsActual")) is None and str(r.get("date") or "") >= today
    ]
    last = reported[-1] if reported else None
    following = upcoming[0] if upcoming else None

    actual = number_or_none((last or {}).get("epsActual"))
    estimate = number_or_none((last or {}).get("epsEstimate"))

    return {
        "ticker_symbol": ticker_symbol,
        "last_reported_on": (last or {}).get("date"),
        "last_eps_actual": actual,
        "last_eps_estimate": estimate,
        # Stated rather than left to the reader, since beating or missing is the point of the row.
        "last_eps_surprise": (
            round(actual - estimate, 4) if actual is not None and estimate is not None else None
        ),
        "next_report_on": (following or {}).get("date"),
        "next_eps_estimate": number_or_none((following or {}).get("epsEstimate")),
        # Finnhub marks whether a report lands before the open or after the close.
        "next_report_timing": (following or {}).get("hour"),
        "days_until_next_report": _days_until((following or {}).get("date"), today),
    }


## Count days from today to a report date, or None when there is no date to count to.
## The number is what makes a row useful next to a contract that expires in thirty-eight days.
def _days_until(report_date, today):
    if not report_date:
        return None

    try:
        return (datetime.fromisoformat(str(report_date)).date() - datetime.fromisoformat(today).date()).days
    except (TypeError, ValueError):
        return None


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

    for ticker_symbol in earnings_tickers():
        try:
            summary = summarize_reports(ticker_symbol, fetch_ticker_earnings(ticker_symbol, session))
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

    return sorted(rows, key=lambda row: (row.get("next_report_on") is None, row.get("next_report_on") or ""))


## Return one company's stored earnings record, or None when it has never been fetched.
## Candidate cards use this to say how close a report is without reloading the whole table.
def get_ticker_earnings(ticker_symbol):
    return get_item(EARNINGS_PK, earnings_sort_key(ticker_symbol))
