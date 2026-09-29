## Verify the unattended scans: what the model is asked, and when a slot refuses to run.
##
## Nobody watches these, so the guards matter as much as the review. A slot must not run
## on a closed market, must not run twice for the same day, and must never invent picks
## when the model is unavailable. The prompt must also keep each trade type distinct,
## since one call now judges all three at once.

import unittest
from unittest.mock import Mock, patch

import pandas as pd

from backend.strategy import triage_jobs
from backend.strategy.daily_triage import (
    MAX_PICKS,
    TRIAGE_SCHEMA,
    build_triage_prompt,
    review_daily_candidates,
)

PUTS = pd.DataFrame([{
    "tickerSymbol": "INTC", "contractSymbol": "INTC261106P00095000", "expiration": "2026-11-06",
    "DTE": 38, "strike": 95.0, "currentStockPrice": 104.0, "delta": -0.25, "ivPercent": 58.0,
    "bid": 2.10, "ask": 2.20, "spread": 0.10, "bidSize": 8, "askSize": 8,
    "premiumIfSoldAtBid": 210.0, "cashRequired": 9500.0, "breakevenPrice": 92.9,
    "returnOnCashPercent": 2.21,
}])
CALLS = pd.DataFrame([{
    "tickerSymbol": "AAPL", "contractSymbol": "AAPL261106C00250000", "expiration": "2026-11-06",
    "DTE": 38, "strike": 250.0, "currentStockPrice": 232.0, "delta": 0.24, "ivPercent": 31.0,
    "bid": 2.40, "ask": 2.50, "spread": 0.10, "bidSize": 5, "askSize": 5,
    "premiumIfSoldAtBid": 240.0, "costBasis": 197.0, "breakevenPrice": 194.6,
    "maxProfitIfCalledAway": 5540.0, "returnOnCashPercent": 1.03,
}])
STOCKS = pd.DataFrame([{
    "tickerSymbol": "SPY", "currentStockPrice": 771.0, "percentChange1Day": 0.5,
    "percentChange5Day": 1.3, "percentChange1Month": 0.7, "percentChangeYTD": 12.9,
    "sharesHeld": None, "costBasis": None, "unrealizedReturnPercent": None,
}])
OFFERED = {"cash_secured_put": PUTS, "covered_call": CALLS, "equity": STOCKS}


class TriagePromptTests(unittest.TestCase):
    ## Every trade type reaches the model labelled, so one call can rank across them.
    def test_prompt_carries_each_strategy_separately(self):
        prompt = build_triage_prompt(OFFERED, {}, {}, {}, {})

        for key in ("cash_secured_put", "covered_call", "equity"):
            self.assertIn(key, prompt)
        self.assertIn("INTC261106P00095000", prompt)
        self.assertIn("AAPL261106C00250000", prompt)
        self.assertIn('"ticker_symbol": "SPY"', prompt)

    ## The prompt states what each kind of trade actually commits, which is what ranking depends on.
    def test_prompt_states_what_each_trade_type_commits(self):
        prompt = build_triage_prompt(OFFERED, {}, {}, {}, {})

        self.assertIn("commits cash and the obligation to buy", prompt)
        self.assertIn("caps their upside at the strike", prompt)
        self.assertIn("advisory only", prompt)
        self.assertIn("choosing none is correct", prompt)

    ## A trade type with nothing to offer is explained rather than silently absent.
    def test_skipped_strategies_are_explained(self):
        prompt = build_triage_prompt(
            {"cash_secured_put": PUTS}, {"covered_call": "No tickers currently qualify for a covered call."},
            {}, {}, {},
        )

        self.assertIn("offering nothing right now", prompt)
        self.assertIn("No tickers currently qualify for a covered call.", prompt)

    ## A later slot is told what earlier ones picked, so it can report change instead of repeating.
    def test_earlier_picks_are_supplied_to_later_slots(self):
        prompt = build_triage_prompt(
            OFFERED, {}, {}, {}, {},
            earlier_picks=[{"slot": "open", "picks": [{"identifier": "INTC261106P00095000"}]}],
        )

        self.assertIn("already reported these earlier today", prompt)
        self.assertIn("rather than repeating", prompt)

    ## Memory is compacted before it is sent, because raw episodes carry whole past market contexts.
    def test_memory_is_compacted_into_the_prompt(self):
        # One episode shaped like the real thing: the lesson is small, the nested history is not.
        memory = {
            "relevant_episodes": [{
                "recommendation_run_id": "run-1",
                "ticker_symbol": "INTC",
                "contract_symbol": "INTC261106P00095000",
                "user_decision": {"action": "place_paper_order", "note": ""},
                "market_context": {"news_and_earnings": [
                    {"headline": f"filler headline {n}", "summary": "x" * 900} for n in range(40)
                ]},
            }],
        }

        prompt = build_triage_prompt(OFFERED, {}, {}, {}, memory)

        # The episode still reaches the model, but not the 36,000 characters of old news inside it.
        self.assertIn("INTC261106P00095000", prompt)
        self.assertNotIn("filler headline 39", prompt)
        self.assertLess(len(prompt), 20000)

    ## Each pick must carry what the user needs hours later, including what would invalidate it.
    def test_schema_requires_a_staleness_note_on_every_pick(self):
        fields = TRIAGE_SCHEMA["properties"]["picks"]["items"]["required"]

        self.assertIn("what_would_change_it", fields)
        self.assertIn("key_risk", fields)
        self.assertIn("strategy_key", fields)


class TriageReviewTests(unittest.TestCase):
    ## With no model there is no deterministic way to rank a put against a stock, so nothing is picked.
    @patch("backend.strategy.daily_triage.get_openai_client", return_value=None)
    def test_no_model_means_no_picks_rather_than_invented_ones(self, _client):
        triage = review_daily_candidates(OFFERED, {}, {}, {}, {})

        self.assertEqual(triage["picks"], [])
        self.assertEqual(triage["ai_error_code"], "not_configured")

    ## A reply cut off by the output budget is reported, not parsed into garbage.
    @patch("backend.strategy.daily_triage.get_openai_client")
    def test_a_cut_off_reply_reports_itself(self, get_client):
        client = Mock()
        client.responses.create.return_value = Mock(status="incomplete", incomplete_details=Mock(reason="max_output_tokens"))
        get_client.return_value = client

        triage = review_daily_candidates(OFFERED, {}, {}, {}, {})

        self.assertEqual(triage["picks"], [])
        self.assertEqual(triage["ai_error_code"], "incomplete_response")

    ## However many the model returns, the day reports at most three.
    @patch("backend.strategy.daily_triage.get_openai_client")
    def test_picks_are_capped(self, get_client):
        pick = {"strategy_key": "cash_secured_put", "identifier": "X", "headline": "h",
                "why_now": "w", "key_risk": "k", "what_would_change_it": "c"}
        client = Mock()
        client.responses.create.return_value = Mock(
            status="completed",
            output_text='{"market_read":"calm","picks":' + str([pick] * 6).replace("'", '"') + ',"passed_over":"rest"}',
            usage=None,
        )
        get_client.return_value = client

        triage = review_daily_candidates(OFFERED, {}, {}, {}, {})

        self.assertEqual(len(triage["picks"]), MAX_PICKS)

    ## Nothing to offer means nothing to ask the model about, and no call is made.
    @patch("backend.strategy.daily_triage.get_openai_client")
    def test_no_candidates_makes_no_model_call(self, get_client):
        triage = review_daily_candidates({}, {"cash_secured_put": "no cash"}, {}, {}, {})

        self.assertEqual(triage["picks"], [])
        get_client.assert_not_called()


class TriageSlotGuardTests(unittest.TestCase):
    ## A holiday or an early close looks like a normal weekday to cron, so the broker decides.
    @patch("backend.strategy.triage_jobs.create_trading_client")
    @patch("backend.strategy.triage_jobs.get_user_broker_credentials")
    @patch("backend.strategy.triage_jobs.get_item", return_value=None)
    def test_a_closed_market_does_no_work(self, _existing, credentials, trading_client):
        credentials.return_value = {"broker": "alpaca", "api_key": "k", "secret_key": "s"}
        trading_client.return_value = Mock(get_clock=Mock(return_value=Mock(is_open=False)))

        result = triage_jobs.run_triage_slot("user-1", "open")

        self.assertEqual(result["skipped"], "market_closed")

    ## A slot that already ran today does nothing again, so a repeated delivery is harmless.
    @patch("backend.strategy.triage_jobs.get_user_broker_credentials")
    @patch("backend.strategy.triage_jobs.get_item", return_value={"sk": "HIGHLIGHT#2026-09-29#open"})
    def test_a_slot_only_runs_once_a_day(self, _existing, credentials):
        result = triage_jobs.run_triage_slot("user-1", "open")

        self.assertEqual(result["skipped"], "slot_already_ran")
        credentials.assert_not_called()

    ## An account with no broker connected is reported rather than crashing the fan-out.
    @patch("backend.strategy.triage_jobs.get_user_broker_credentials", return_value=None)
    @patch("backend.strategy.triage_jobs.get_item", return_value=None)
    def test_an_unconnected_account_is_skipped(self, _existing, _credentials):
        result = triage_jobs.run_triage_slot("user-1", "open")

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "broker_not_connected")

    ## An unknown slot name is refused rather than silently scanning under the wrong label.
    def test_an_unknown_slot_is_refused(self):
        with self.assertRaisesRegex(ValueError, "Unknown scan slot"):
            triage_jobs.dispatch_scheduled_triage("teatime")


if __name__ == "__main__":
    unittest.main()
