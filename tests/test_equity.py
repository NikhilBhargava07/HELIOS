## Verify stock recommendations: one batch of price history, no orders, and no invented ranking.
##
## Equity is the first strategy that is not an option, so these tests also confirm
## the shared pipeline no longer assumes contracts: candidates are gathered in one
## request rather than per ticker, saved under a ticker instead of a contract
## symbol, and refused at the placement gate because HELIOS only advises on stocks.

import json
import unittest
from unittest.mock import Mock, patch

import pandas as pd

from backend.api.services import candidates_to_records
from backend.memory.recommendations import save_recommendation_run
from backend.strategy.equity import EQUITY, find_candidates, local_review, secure_candidate
from backend.strategy.recommender import get_recommendation_results
from backend.strategy.review_prompt import build_review_prompt
from backend.strategy.spec import ScanContext


## Build a scan context carrying prices and the user's holdings.
def scan_context(prices, holdings=None, stock_data_client=None):
    return ScanContext(
        available_capital=None,
        latest_prices={ticker: {"price": price} for ticker, price in prices.items()},
        portfolio_context={"holdings": holdings or {}},
        stock_data_client=stock_data_client or Mock(),
        option_data_client=None,
    )


## Return one trend record shaped like the market-trends helper produces.
def trend(ticker, one_day=1.0, five_day=2.0, one_month=3.0, ytd=4.0):
    return {"ticker": ticker, "1d": one_day, "5d": five_day, "1m": one_month, "ytd": ytd}


class EquityCandidateTests(unittest.TestCase):
    ## Every approved ticker's history comes from one broker request, not one request each.
    @patch("backend.strategy.equity.get_market_trends")
    def test_candidates_are_built_from_a_single_batch_request(self, get_trends):
        tickers = ["AAPL", "MSFT", "NVDA"]
        get_trends.return_value = [trend(ticker) for ticker in tickers]

        scan = find_candidates(
            EQUITY,
            tickers,
            scan_context({"AAPL": 200.0, "MSFT": 400.0, "NVDA": 120.0}),
        )

        get_trends.assert_called_once()
        self.assertEqual(list(scan.candidates["tickerSymbol"]), tickers)
        self.assertEqual(scan.errors, ())

    ## A ticker HELIOS cannot price or has no history for is dropped rather than shown blank.
    @patch("backend.strategy.equity.get_market_trends")
    def test_tickers_without_readable_history_are_dropped(self, get_trends):
        get_trends.return_value = [trend("AAPL"), trend("MSFT", one_day=None)]

        scan = find_candidates(
            EQUITY,
            ["AAPL", "MSFT", "NVDA"],
            # NVDA has history but no current price.
            scan_context({"AAPL": 200.0, "MSFT": 400.0}),
        )

        self.assertEqual(list(scan.candidates["tickerSymbol"]), ["AAPL"])
        self.assertEqual(scan.errors, ("MSFT:no_price_history", "NVDA:no_price_history"))

    ## An existing position is attached, because holding a stock and buying it are different questions.
    @patch("backend.strategy.equity.get_market_trends")
    def test_existing_holdings_are_attached_with_unrealized_return(self, get_trends):
        get_trends.return_value = [trend("AAPL")]

        scan = find_candidates(
            EQUITY,
            ["AAPL"],
            scan_context({"AAPL": 220.0}, holdings={"AAPL": {"shares": 100, "cost_basis": 200.0}}),
        )

        row = scan.candidates.iloc[0]
        self.assertEqual(row["sharesHeld"], 100)
        self.assertEqual(row["costBasis"], 200.0)
        self.assertAlmostEqual(row["unrealizedReturnPercent"], 10.0)

    ## A stock the user does not own reports no position rather than a zero one.
    @patch("backend.strategy.equity.get_market_trends")
    def test_unheld_stock_reports_no_position(self, get_trends):
        get_trends.return_value = [trend("AAPL")]

        row = find_candidates(EQUITY, ["AAPL"], scan_context({"AAPL": 220.0})).candidates.iloc[0]

        self.assertIsNone(row["sharesHeld"])
        self.assertIsNone(row["unrealizedReturnPercent"])


class EquityReviewTests(unittest.TestCase):
    ## Every approved ticker reaches the model, since dropping some would be a silent recommendation.
    @patch("backend.strategy.equity.get_market_trends")
    @patch("backend.strategy.recommender.build_memory_context", return_value={})
    @patch("backend.strategy.recommender.build_candidate_review_context", return_value={})
    @patch("backend.strategy.recommender.get_latest_stock_prices")
    @patch("backend.strategy.ai_review.get_openai_client", return_value=None)
    def test_all_approved_tickers_reach_the_review(self, _client, prices, _market, _memory, get_trends):
        tickers = EQUITY.eligible_tickers()
        prices.return_value = {ticker: {"price": 100.0} for ticker in tickers}
        get_trends.return_value = [trend(ticker) for ticker in tickers]

        results = get_recommendation_results(
            EQUITY,
            "user-1",
            total_capital=100_000,
            # Neither the position cap nor available capital applies to advice.
            current_open_positions=5,
            stock_data_client=Mock(),
            option_data_client=None,
        )

        self.assertEqual(len(results["candidates"]), len(tickers))

    ## Without the model there are no hard stock rules to fall back on, so nothing is recommended.
    def test_local_fallback_refuses_to_name_a_stock(self):
        review = local_review("AAPL", None)

        self.assertEqual(review["decision"], "reject_all")
        self.assertIsNone(review["selected_contract"])
        self.assertIn("no hard rules", review["risk_note"])

    ## The prompt states the trend facts and that HELIOS takes no action on stocks.
    @patch("backend.strategy.equity.get_market_trends")
    def test_prompt_carries_trend_facts_and_the_advisory_rule(self, get_trends):
        get_trends.return_value = [trend("AAPL")]
        candidates = find_candidates(EQUITY, ["AAPL"], scan_context({"AAPL": 220.0})).candidates

        prompt = build_review_prompt(EQUITY, candidates, EQUITY.strategy_rules)

        self.assertIn('"percent_change_ytd": 4.0', prompt)
        self.assertIn('"action_taken": "none"', prompt)
        self.assertIn("HELIOS will not place any stock order", prompt)


class EquityRecordValueTests(unittest.TestCase):
    ## A stock the user does not own must save as absent, not as a NaN that breaks JSON and DynamoDB.
    def test_missing_numbers_are_saved_as_absent(self):
        records = candidates_to_records(pd.DataFrame([
            {"tickerSymbol": "AAPL", "currentStockPrice": 232.15, "sharesHeld": 100, "costBasis": 197.0},
            {"tickerSymbol": "MSFT", "currentStockPrice": 418.90, "sharesHeld": None, "costBasis": None},
        ]))

        self.assertIsNone(records[1]["sharesHeld"])
        self.assertEqual(records[0]["sharesHeld"], 100)
        # Invalid JSON would reach the browser and DynamoDB would reject the write.
        json.dumps(records, allow_nan=False)


class EquityPlacementTests(unittest.TestCase):
    ## Placing a stock order is refused by design, not by the absence of code to do it.
    def test_placement_is_refused(self):
        with self.assertRaisesRegex(ValueError, "does not place stock orders"):
            secure_candidate({"tickerSymbol": "AAPL"}, context=None)


class EquityRecordTests(unittest.TestCase):
    ## A stock has no contract symbol, so its saved candidate is identified by ticker.
    @patch("backend.memory.recommendations.put_items")
    @patch("backend.memory.recommendations.put_item")
    def test_saved_candidates_are_identified_by_ticker(self, _put_item, put_items):
        run = save_recommendation_run(
            "user-1",
            [{"tickerSymbol": "AAPL", "currentStockPrice": 220.0}],
            {"decision": "approve"},
            strategy_rules=EQUITY.strategy_rules,
            candidate_id_column=EQUITY.candidate_id_column,
        )

        stored = next(
            item for item in put_items.call_args.args[0]
            if item.get("item_type") == "recommendation_candidate"
        )
        self.assertEqual(stored["sk"], "CANDIDATE#AAPL")
        self.assertEqual(stored["candidate_id"], "AAPL")
        self.assertIsNone(stored["contract_symbol"])
        self.assertEqual(run["candidates"][0]["tickerSymbol"], "AAPL")


if __name__ == "__main__":
    unittest.main()
