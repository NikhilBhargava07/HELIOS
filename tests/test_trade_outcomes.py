## Verify that CSP outcomes require factual broker lifecycle evidence.

import unittest
from unittest.mock import patch

from backend.memory.outcomes import finalize_csp_trade_outcomes


class TradeOutcomeTests(unittest.TestCase):
    ## Calculate retained premium from the exact filled buy-to-close debit.
    @patch("backend.memory.outcomes.close_fallback_order_position")
    @patch("backend.memory.outcomes.put_item")
    @patch("backend.memory.outcomes.get_item", return_value=None)
    @patch("backend.memory.outcomes.get_recent_outcome_snapshots", return_value=[])
    @patch("backend.memory.outcomes.query_items")
    def test_buy_to_close_completes_option_outcome(
        self,
        query_items,
        snapshots,
        get_item,
        put_item,
        close_position,
    ):
        query_items.return_value = [self._opening_order()]
        broker_orders = [{
            "id": "close-1",
            "symbol": "AAPL260821P00200000",
            "side": "buy",
            "position_intent": "buy_to_close",
            "status": "filled",
            "filled_qty": "1",
            "filled_avg_price": "0.75",
            "filled_at": "2026-08-10T12:00:00+00:00",
        }]

        result = finalize_csp_trade_outcomes(
            "user-1",
            live_positions=[],
            broker_orders=broker_orders,
            option_activities=[],
        )

        self.assertEqual(result["completed"], 1)
        outcome = put_item.call_args.args[0]
        self.assertEqual(outcome["resolution_type"], "bought_to_close")
        self.assertEqual(outcome["opening_credit"], 200)
        self.assertEqual(outcome["closing_debit"], 75)
        self.assertEqual(outcome["option_realized_pnl"], 125)
        self.assertEqual(outcome["premium_retained_percent"], 62.5)
        self.assertFalse(outcome["underlying_outcome_pending"])
        close_position.assert_called_once()

    ## Preserve assignment as a nuanced option outcome with unresolved stock risk.
    @patch("backend.memory.outcomes.close_fallback_order_position")
    @patch("backend.memory.outcomes.put_item")
    @patch("backend.memory.outcomes.get_item", return_value=None)
    @patch("backend.memory.outcomes.get_recent_outcome_snapshots", return_value=[])
    @patch("backend.memory.outcomes.query_items")
    def test_assignment_keeps_underlying_outcome_pending(
        self,
        query_items,
        snapshots,
        get_item,
        put_item,
        close_position,
    ):
        query_items.return_value = [self._opening_order()]

        result = finalize_csp_trade_outcomes(
            "user-1",
            live_positions=[],
            broker_orders=[],
            option_activities=[{
                "id": "activity-1",
                "activity_type": "OPASN",
                "symbol": "AAPL260821P00200000",
                "date": "2026-08-22",
            }],
        )

        self.assertEqual(result["completed"], 1)
        outcome = put_item.call_args.args[0]
        self.assertTrue(outcome["assigned"])
        self.assertTrue(outcome["underlying_outcome_pending"])
        self.assertEqual(outcome["assignment_cash_obligation"], 20_000)
        self.assertEqual(outcome["effective_share_cost"], 198)
        self.assertEqual(outcome["option_realized_pnl"], 200)

    ## Refuse to infer a terminal result merely because the contract vanished.
    @patch("backend.memory.outcomes.close_fallback_order_position")
    @patch("backend.memory.outcomes.put_item")
    @patch("backend.memory.outcomes.get_item", return_value=None)
    @patch("backend.memory.outcomes.get_recent_outcome_snapshots", return_value=[])
    @patch("backend.memory.outcomes.query_items")
    def test_missing_position_without_evidence_stays_unresolved(
        self,
        query_items,
        snapshots,
        get_item,
        put_item,
        close_position,
    ):
        query_items.return_value = [self._opening_order()]

        result = finalize_csp_trade_outcomes(
            "user-1",
            live_positions=[],
            broker_orders=[],
            option_activities=[],
        )

        self.assertEqual(result["completed"], 0)
        self.assertEqual(len(result["unresolved"]), 1)
        put_item.assert_not_called()
        close_position.assert_not_called()

    ## Ignore lifecycle evidence that predates the opening order for the same contract.
    @patch("backend.memory.outcomes.close_fallback_order_position")
    @patch("backend.memory.outcomes.put_item")
    @patch("backend.memory.outcomes.get_item", return_value=None)
    @patch("backend.memory.outcomes.get_recent_outcome_snapshots", return_value=[])
    @patch("backend.memory.outcomes.query_items")
    def test_old_lifecycle_activity_does_not_finalize_new_trade(
        self,
        query_items,
        snapshots,
        get_item,
        put_item,
        close_position,
    ):
        query_items.return_value = [self._opening_order()]

        result = finalize_csp_trade_outcomes(
            "user-1",
            live_positions=[],
            broker_orders=[],
            option_activities=[{
                "id": "old-activity",
                "activity_type": "OPEXP",
                "symbol": "AAPL260821P00200000",
                "date": "2026-07-01",
            }],
        )

        self.assertEqual(result["completed"], 0)
        self.assertEqual(len(result["unresolved"]), 1)
        put_item.assert_not_called()

    ## Build one filled opening CSP order shared by lifecycle tests.
    @staticmethod
    def _opening_order():
        return {
            "id": "open-1",
            "created_at": "2026-08-01T12:00:00+00:00",
            "alpaca_filled_at": "2026-08-01T12:01:00+00:00",
            "alpaca_filled_qty": "1",
            "alpaca_order_id": "alpaca-open-1",
            "recommendation_run_id": "run-1",
            "strategy": "cash-secured put",
            "status": "filled",
            "contract_symbol": "AAPL260821P00200000",
            "ticker_symbol": "AAPL",
            "expiration": "2026-08-21",
            "strike": 200,
            "premium_received": 200,
            "breakeven_price": 198,
            "entry_factors": {"delta": -0.25},
        }


if __name__ == "__main__":
    unittest.main()
