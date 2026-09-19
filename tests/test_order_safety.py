## Verify CSP order idempotency, final quote checks, and fill reconciliation.

import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock, patch

from backend.api.services import (
    active_short_option_orders,
    prepare_candidate_for_paper_order,
    require_fresh_recommendation,
)
from backend.strategy.cash_secured_put import CASH_SECURED_PUT, economics
from backend.broker.trading import (
    build_helios_client_order_id,
    get_option_lifecycle_activities,
    refresh_candidate_option_quote,
)
from backend.memory.trades import reconcile_paper_orders


## Run the placement gate for one cash-secured put against a mocked broker account.
def place_cash_secured_put(get_orders, get_account, get_positions):
    return prepare_candidate_for_paper_order(
        "user-a",
        {
            "strategy_rules": {"strategy": "cash-secured put"},
            "created_at": datetime.now(timezone.utc).isoformat(),
        },
        {
            "contractSymbol": "AAPL260821P00200000",
            "tickerSymbol": "AAPL",
            "strike": 200,
            "currentStockPrice": 205,
            "DTE": 35,
            "cashRequired": 20_000,
            "premiumIfSoldAtBid": 100,
            "breakevenPrice": 199,
            "returnOnCashPercent": 0.5,
        },
        "helios-new-order",
        Mock(),
        Mock(),
    )


class OrderSafetyTests(unittest.TestCase):
    ## Generate the same opaque Alpaca id for retries of one recommendation action.
    def test_client_order_id_is_deterministic(self):
        first = build_helios_client_order_id("user-a", "run-1", "AAPL260821P00200000")
        second = build_helios_client_order_id("user-a", "run-1", "AAPL260821P00200000")
        different = build_helios_client_order_id("user-a", "run-2", "AAPL260821P00200000")

        self.assertEqual(first, second)
        self.assertNotEqual(first, different)
        self.assertLessEqual(len(first), 48)

    ## Require a new scan when the candidate's non-quote evidence is too old.
    def test_stale_recommendation_is_rejected(self):
        old_time = datetime.now(timezone.utc) - timedelta(hours=1)

        with self.assertRaisesRegex(ValueError, "stale"):
            require_fresh_recommendation(
                {"created_at": old_time.isoformat()},
                maximum_age_seconds=60,
            )

    ## Count every unfilled short option order, of either type, as live exposure with its contract parsed.
    def test_active_short_orders_parse_each_pending_sell(self):
        orders = active_short_option_orders([
            {"symbol": "AAPL260821P00200000", "side": "sell", "status": "accepted"},
            {"symbol": "AAPL260821C00200000", "side": "sell", "status": "new"},
            # Filled, bought, or unparseable orders commit nothing further.
            {"symbol": "AAPL260821P00195000", "side": "sell", "status": "filled"},
            {"symbol": "AAPL260821P00190000", "side": "buy", "status": "accepted"},
            {"symbol": "not-an-option", "side": "sell", "status": "accepted"},
        ])

        self.assertEqual(
            [(order["contract"]["option_type"], order["contract"]["strike"]) for order in orders],
            [("put", 200.0), ("call", 200.0)],
        )

    ## Treat a matching broker client id as a successful retry without another submission path.
    @patch("backend.api.services.refresh_candidate_option_quote")
    @patch("backend.api.services.get_paper_positions")
    @patch("backend.api.services.get_paper_account_summary")
    @patch("backend.api.services.get_paper_orders")
    def test_existing_order_short_circuits_placement_checks(
        self,
        get_orders,
        get_account,
        get_positions,
        refresh_quote,
    ):
        existing = {
            "id": "alpaca-1",
            "client_order_id": "helios-repeat",
            "status": "accepted",
        }
        get_orders.return_value = [existing]

        result = prepare_candidate_for_paper_order(
            "user-a",
            {"created_at": "invalid-but-unused"},
            {"contractSymbol": "AAPL260821P00200000"},
            "helios-repeat",
            Mock(),
            Mock(),
        )

        self.assertEqual(result["existing_order"], existing)
        get_account.assert_not_called()
        get_positions.assert_not_called()
        refresh_quote.assert_not_called()

    ## Count open puts and pending sell orders together against the position limit.
    @patch("backend.api.services.get_paper_positions")
    @patch("backend.api.services.get_paper_account_summary")
    @patch("backend.api.services.get_paper_orders")
    def test_pending_orders_count_toward_the_position_limit(self, get_orders, get_account, get_positions):
        pending = {"symbol": "MSFT260821P00400000", "side": "sell", "status": "accepted"}
        get_orders.return_value = [pending]
        get_account.return_value = {"available_csp_cash": 500_000, "portfolio_value": 500_000}
        get_positions.return_value = [
            {"strategy": "cash-secured put", "contract_symbol": f"AAPL260821P0019{index}000", "cash_required": 20_000}
            for index in range(4)
        ]

        with self.assertRaisesRegex(ValueError, "includes pending orders"):
            place_cash_secured_put(get_orders, get_account, get_positions)

    ## Refuse a put the account can no longer secure, whatever the scan showed.
    @patch("backend.api.services.get_paper_positions")
    @patch("backend.api.services.get_paper_account_summary")
    @patch("backend.api.services.get_paper_orders")
    def test_placement_refuses_a_put_beyond_current_buying_power(self, get_orders, get_account, get_positions):
        get_orders.return_value = []
        get_account.return_value = {"available_csp_cash": 5_000, "portfolio_value": 500_000}
        get_positions.return_value = []

        with self.assertRaisesRegex(ValueError, r"requires \$20,000.00, but current strategy and broker limits allow \$5,000.00"):
            place_cash_secured_put(get_orders, get_account, get_positions)

    ## Recalculate premium, breakeven, and ROC from the exact quote checked before submission.
    def test_latest_quote_replaces_scan_price(self):
        quote = SimpleNamespace(
            model_dump=lambda mode="json": {
                "bid_price": "1.25",
                "ask_price": "1.35",
                "bid_size": "4",
                "ask_size": "3",
                "timestamp": "2026-08-02T12:00:00Z",
            }
        )
        option_client = Mock()
        option_client.get_option_latest_quote.return_value = {
            "AAPL260821P00200000": quote,
        }
        candidate = {
            "contractSymbol": "AAPL260821P00200000",
            "strike": 200,
            "currentStockPrice": 205,
            "DTE": 35,
            "cashRequired": 20_000,
            "premiumIfSoldAtBid": 100,
            "breakevenPrice": 199,
            "returnOnCashPercent": 0.5,
        }

        refreshed = refresh_candidate_option_quote(
            candidate,
            option_client,
            CASH_SECURED_PUT,
            economics,
        )

        self.assertEqual(refreshed["premiumIfSoldAtBid"], 125)
        self.assertEqual(refreshed["breakevenPrice"], 198.75)
        self.assertAlmostEqual(refreshed["returnOnCashPercent"], 0.625)

    ## Create the fallback position when reconciliation observes a later broker fill.
    @patch("backend.memory.trades.put_item")
    @patch("backend.memory.trades.get_item")
    def test_reconciliation_promotes_filled_order_to_position(self, get_item, put_item):
        saved_order = {
            "pk": "USER#user-a",
            "sk": "ORDER#saved",
            "id": "local-order-1",
            "strategy": "cash-secured put",
            "contract_symbol": "AAPL260821P00200000",
            "ticker_symbol": "AAPL",
            "expiration": "2026-08-21",
            "strike": 200,
            "premium_received": 100,
            "cash_required": 20_000,
            "breakeven_price": 199,
            "status": "accepted",
        }
        get_item.side_effect = [
            {"user_order_sk": "ORDER#saved"},
            saved_order,
        ]

        count = reconcile_paper_orders("user-a", [{
            "id": "alpaca-order-1",
            "status": "filled",
            "filled_qty": "1",
            "filled_avg_price": "1.40",
            "filled_at": "2026-08-02T12:05:00Z",
        }])

        self.assertEqual(count, 1)
        updated_order = put_item.call_args_list[0].args[0]
        position = put_item.call_args_list[1].args[0]
        self.assertEqual(updated_order["status"], "filled")
        self.assertEqual(updated_order["premium_received"], 140)
        self.assertEqual(updated_order["breakeven_price"], 198.60)
        self.assertEqual(position["sk"], "POSITION#ORDER#local-order-1")
        self.assertEqual(position["premium_received"], 140)
        self.assertEqual(position["breakeven_price"], 198.60)
        self.assertEqual(position["filled_at"], "2026-08-02T12:05:00Z")

    ## Retain successful lifecycle evidence when one Alpaca activity subtype is unavailable.
    def test_lifecycle_activity_lookup_allows_partial_success(self):
        trading_client = Mock()
        trading_client.get.side_effect = [
            RuntimeError("assignment endpoint unavailable"),
            [{
                "id": "expiry-1",
                "symbol": "AAPL260821P00200000",
                "activity_type": SimpleNamespace(value="OPEXP"),
            }],
            [],
        ]

        activities = get_option_lifecycle_activities(
            after="2026-08-01",
            trading_client=trading_client,
        )

        self.assertEqual(len(activities), 1)
        self.assertEqual(activities[0]["activity_type"], "OPEXP")

    ## Raise when Alpaca supplies no lifecycle endpoint at all so the job can report degraded evidence.
    def test_lifecycle_activity_lookup_reports_total_failure(self):
        trading_client = Mock()
        trading_client.get.side_effect = RuntimeError("activities unavailable")

        with self.assertRaisesRegex(RuntimeError, "activities unavailable"):
            get_option_lifecycle_activities(trading_client=trading_client)


if __name__ == "__main__":
    unittest.main()
