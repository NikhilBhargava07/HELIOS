## Verify that option outcomes require factual broker lifecycle evidence.
##
## Puts and calls end differently, so these tests also cover the wheel: a covered
## call being exercised settles the shares an earlier assignment delivered, and a
## partial match is left pending rather than guessed at.

import unittest
from unittest.mock import patch

from backend.memory.outcomes import finalize_trade_outcomes


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

        result = finalize_trade_outcomes(
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

        result = finalize_trade_outcomes(
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

        result = finalize_trade_outcomes(
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

        result = finalize_trade_outcomes(
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

    ## Build one filled opening covered-call order shared by wheel tests.
    @staticmethod
    def _covered_call_order():
        return {
            "id": "call-1",
            "created_at": "2026-08-01T12:00:00+00:00",
            "alpaca_filled_at": "2026-08-01T12:01:00+00:00",
            "alpaca_filled_qty": "1",
            "alpaca_order_id": "alpaca-call-1",
            "strategy": "covered call",
            "status": "filled",
            "contract_symbol": "AAPL260821C00210000",
            "ticker_symbol": "AAPL",
            "expiration": "2026-08-21",
            "strike": 210,
            "premium_received": 250,
            # Shares secure it, so it committed no cash and cost 198 each.
            "cash_required": 0,
            "cost_basis": 198,
            "breakeven_price": 195.5,
            "entry_factors": {"delta": 0.25},
        }

    ## Build one still-pending put assignment that delivered 100 shares at an effective 198.
    @staticmethod
    def _pending_assignment(quantity=1):
        return {
            "pk": "USER#user-1",
            "sk": "OUTCOME#2026-07-02T00:00:00+00:00#put-1",
            "status": "complete",
            "assigned": True,
            "underlying_outcome_pending": True,
            "ticker_symbol": "AAPL",
            "quantity": quantity,
            "effective_share_cost": 198.0,
            "completed_at": "2026-07-02T00:00:00+00:00",
        }

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


class CoveredCallOutcomeTests(unittest.TestCase):
    ## Route the saved-order query and the pending-assignment query to their own fixtures.
    @staticmethod
    def _queries(orders, outcomes):
        def query(_partition, prefix, **_kwargs):
            return orders if prefix == "ORDER#" else outcomes
        return query

    ## Exercise delivers the shares, so the call settles a share result instead of creating a cash obligation.
    @patch("backend.memory.outcomes.close_fallback_order_position")
    @patch("backend.memory.outcomes.put_item")
    @patch("backend.memory.outcomes.get_item", return_value=None)
    @patch("backend.memory.outcomes.get_recent_outcome_snapshots", return_value=[])
    @patch("backend.memory.outcomes.query_items")
    def test_called_away_call_reports_the_share_result(
        self, query_items, _snapshots, _get_item, put_item, _close_position,
    ):
        query_items.side_effect = self._queries([TradeOutcomeTests._covered_call_order()], [])

        result = finalize_trade_outcomes(
            "user-1",
            live_positions=[],
            broker_orders=[],
            option_activities=[{
                "id": "activity-call",
                "activity_type": "OPASN",
                "symbol": "AAPL260821C00210000",
                "date": "2026-08-22",
            }],
        )

        self.assertEqual(result["completed"], 1)
        outcome = put_item.call_args.args[0]
        self.assertTrue(outcome["assigned"])
        self.assertEqual(outcome["shares_called_away"], 100)
        self.assertEqual(outcome["share_sale_proceeds"], 21_000)
        # Sold at 210 shares that really cost 198.
        self.assertEqual(outcome["share_realized_pnl"], 1_200)
        self.assertEqual(outcome["option_realized_pnl"], 250)
        # Nothing about the shares is left open, and no cash was ever owed.
        self.assertFalse(outcome["underlying_outcome_pending"])
        self.assertIsNone(outcome["assignment_cash_obligation"])

    ## Being called away answers the open question left by an earlier assignment, completing the wheel.
    @patch("backend.memory.outcomes.close_fallback_order_position")
    @patch("backend.memory.outcomes.put_item")
    @patch("backend.memory.outcomes.get_item", return_value=None)
    @patch("backend.memory.outcomes.get_recent_outcome_snapshots", return_value=[])
    @patch("backend.memory.outcomes.query_items")
    def test_called_away_shares_settle_the_earlier_assignment(
        self, query_items, _snapshots, _get_item, put_item, _close_position,
    ):
        query_items.side_effect = self._queries(
            [TradeOutcomeTests._covered_call_order()],
            [TradeOutcomeTests._pending_assignment()],
        )

        result = finalize_trade_outcomes(
            "user-1",
            live_positions=[],
            broker_orders=[],
            option_activities=[{
                "id": "activity-call",
                "activity_type": "OPASN",
                "symbol": "AAPL260821C00210000",
                "date": "2026-08-22",
            }],
        )

        self.assertEqual(result["assignments_settled"], 1)
        settled = next(
            item for item in (call.args[0] for call in put_item.call_args_list)
            if item.get("underlying_resolution")
        )
        self.assertFalse(settled["underlying_outcome_pending"])
        self.assertEqual(settled["underlying_realized_pnl"], 1_200)
        self.assertEqual(settled["underlying_evidence"]["covered_call_contract_symbol"], "AAPL260821C00210000")

    ## One contract cannot settle a larger assignment, so the rest stays pending rather than being guessed at.
    @patch("backend.memory.outcomes.close_fallback_order_position")
    @patch("backend.memory.outcomes.put_item")
    @patch("backend.memory.outcomes.get_item", return_value=None)
    @patch("backend.memory.outcomes.get_recent_outcome_snapshots", return_value=[])
    @patch("backend.memory.outcomes.query_items")
    def test_partial_coverage_leaves_the_assignment_pending(
        self, query_items, _snapshots, _get_item, put_item, _close_position,
    ):
        query_items.side_effect = self._queries(
            [TradeOutcomeTests._covered_call_order()],
            # 200 shares were assigned, but only 100 were called away.
            [TradeOutcomeTests._pending_assignment(quantity=2)],
        )

        result = finalize_trade_outcomes(
            "user-1",
            live_positions=[],
            broker_orders=[],
            option_activities=[{
                "id": "activity-call",
                "activity_type": "OPASN",
                "symbol": "AAPL260821C00210000",
                "date": "2026-08-22",
            }],
        )

        self.assertEqual(result["assignments_settled"], 0)
        self.assertNotIn(
            "underlying_resolution",
            " ".join(str(call.args[0]) for call in put_item.call_args_list),
        )

    ## A call that expires worthless keeps the shares, so no earlier assignment is settled.
    @patch("backend.memory.outcomes.close_fallback_order_position")
    @patch("backend.memory.outcomes.put_item")
    @patch("backend.memory.outcomes.get_item", return_value=None)
    @patch("backend.memory.outcomes.get_recent_outcome_snapshots", return_value=[])
    @patch("backend.memory.outcomes.query_items")
    def test_expired_call_keeps_the_shares_and_settles_nothing(
        self, query_items, _snapshots, _get_item, put_item, _close_position,
    ):
        query_items.side_effect = self._queries(
            [TradeOutcomeTests._covered_call_order()],
            [TradeOutcomeTests._pending_assignment()],
        )

        result = finalize_trade_outcomes(
            "user-1",
            live_positions=[],
            broker_orders=[],
            option_activities=[{
                "id": "activity-expiry",
                "activity_type": "OPEXP",
                "symbol": "AAPL260821C00210000",
                "date": "2026-08-22",
            }],
        )

        self.assertEqual(result["completed"], 1)
        self.assertEqual(result["assignments_settled"], 0)
        outcome = put_item.call_args.args[0]
        self.assertFalse(outcome["assigned"])
        self.assertIsNone(outcome["shares_called_away"])
        self.assertEqual(outcome["option_realized_pnl"], 250)


if __name__ == "__main__":
    unittest.main()
