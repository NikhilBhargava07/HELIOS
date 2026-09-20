## Verify event-driven history import, outcome review, and explicit user feedback.

import unittest
from unittest.mock import patch

from backend.memory.feedback import save_trade_feedback
from backend.memory.outcome_review import review_completed_csp_outcomes
from backend.memory.trades import import_filled_csp_order_history


class HistoricalCspImportTests(unittest.TestCase):
    ## Import an explicit filled sell-to-open put with exact broker economics.
    @patch("backend.memory.trades._save_filled_order_position")
    @patch("backend.memory.trades.put_items")
    @patch("backend.memory.trades.query_items", return_value=[])
    def test_imports_filled_sell_to_open_put(
        self,
        query_items,
        put_items,
        save_position,
    ):
        result = import_filled_csp_order_history(
            "user-1",
            [self._broker_order(position_intent="sell_to_open")],
        )

        self.assertEqual(result["imported"], 1)
        saved_order = put_items.call_args.args[0][0]
        self.assertEqual(saved_order["source"], "alpaca_history_import")
        self.assertEqual(saved_order["ticker_symbol"], "AAPL")
        self.assertEqual(saved_order["strike"], 200)
        self.assertEqual(saved_order["premium_received"], 200)
        self.assertEqual(saved_order["cash_required"], 20_000)
        self.assertNotIn("recommendation_run_id", saved_order)
        save_position.assert_called_once()

    ## Refuse to treat a put sale with missing position intent as an opened CSP.
    @patch("backend.memory.trades._save_filled_order_position")
    @patch("backend.memory.trades.put_items")
    @patch("backend.memory.trades.query_items", return_value=[])
    def test_skips_ambiguous_filled_put_sale(
        self,
        query_items,
        put_items,
        save_position,
    ):
        result = import_filled_csp_order_history(
            "user-1",
            [self._broker_order(position_intent=None)],
        )

        self.assertEqual(result["imported"], 0)
        self.assertEqual(result["skipped_ambiguous_put_sales"], 1)
        put_items.assert_not_called()
        save_position.assert_not_called()

    ## Build one normalized Alpaca order shared by historical-import tests.
    @staticmethod
    def _broker_order(position_intent):
        return {
            "id": "alpaca-order-1",
            "client_order_id": "client-1",
            "status": "filled",
            "symbol": "AAPL260821P00200000",
            "side": "sell",
            "position_intent": position_intent,
            "limit_price": "2.10",
            "filled_qty": "1",
            "filled_avg_price": "2.00",
            "submitted_at": "2026-08-01T12:00:00+00:00",
            "filled_at": "2026-08-01T12:01:00+00:00",
        }


class ExplicitTradeFeedbackTests(unittest.TestCase):
    ## Keep subjective satisfaction separate from the order's measured economics.
    @patch("backend.memory.feedback.put_item")
    @patch("backend.memory.feedback.get_paper_order_by_id")
    def test_saves_feedback_against_owned_order(self, get_order, put_item):
        get_order.return_value = {
            "id": "order-1",
            "recommendation_run_id": "run-1",
            "ticker_symbol": "ORCL",
            "contract_symbol": "ORCL260821P00175000",
        }

        feedback = save_trade_feedback(
            "user-1",
            "order-1",
            satisfaction="mixed",
            would_repeat=False,
            assignment_preference="welcome",
            reason_tags=["assignment", "timing", "timing"],
            note="Happy to own the shares, but the entry was too early.",
        )

        self.assertEqual(feedback["satisfaction"], "mixed")
        self.assertEqual(feedback["assignment_preference"], "welcome")
        self.assertEqual(feedback["reason_tags"], ["assignment", "timing"])
        self.assertFalse(feedback["would_repeat"])
        put_item.assert_called_once()

    ## Reject feedback when the order is absent from the authenticated user's partition.
    @patch("backend.memory.feedback.get_paper_order_by_id", return_value=None)
    def test_rejects_unknown_order(self, get_order):
        with self.assertRaisesRegex(ValueError, "Paper order not found"):
            save_trade_feedback(
                "user-1",
                "other-user-order",
                satisfaction="dissatisfied",
                would_repeat=False,
                assignment_preference="avoid",
            )


class CompletedOutcomeReviewTests(unittest.TestCase):
    ## Preserve assignment as a pending stock result even when OpenAI is unavailable.
    @patch("backend.memory.outcome_review.get_openai_client", return_value=None)
    @patch("backend.memory.outcome_review.get_trade_feedback", return_value=[])
    def test_local_review_keeps_assignment_pending(self, feedback, get_client):
        outcome = {
            "opening_order_id": "order-1",
            "ticker_symbol": "ORCL",
            "contract_symbol": "ORCL260821P00175000",
            "assigned": True,
            "option_realized_pnl": 530,
            "assignment_cash_obligation": 17_500,
            "underlying_outcome_pending": True,
            "entry_factors": {"iv_percent": 55},
        }

        reviews = review_completed_csp_outcomes("user-1", [outcome])

        self.assertEqual(reviews[0]["economic_result"], "assigned_pending")
        self.assertEqual(reviews[0]["review_source"], "local_fallback")
        self.assertEqual(reviews[0]["ai_error_code"], "not_configured")
        self.assertTrue(reviews[0]["drivers"])

    ## Once the shares are called away the result is final, so the trade stops being reported as pending.
    @patch("backend.memory.outcome_review.get_openai_client", return_value=None)
    @patch("backend.memory.outcome_review.get_trade_feedback", return_value=[])
    def test_local_review_settles_a_called_away_assignment(self, feedback, get_client):
        outcome = {
            "opening_order_id": "order-1",
            "ticker_symbol": "ORCL",
            "contract_symbol": "ORCL260821P00175000",
            "assigned": True,
            "option_realized_pnl": 530,
            "assignment_cash_obligation": 17_500,
            "underlying_outcome_pending": False,
            "underlying_resolution": "called_away",
            "underlying_realized_pnl": 400,
            "entry_factors": {"iv_percent": 55},
        }

        reviews = review_completed_csp_outcomes("user-1", [outcome])

        self.assertEqual(reviews[0]["economic_result"], "profit")


if __name__ == "__main__":
    unittest.main()
