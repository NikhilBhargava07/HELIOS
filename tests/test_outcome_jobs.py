## Verify scheduled CSP observation dispatch behavior.

import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from backend.memory.outcome_jobs import (
    create_outcome_observation_job,
    dispatch_scheduled_outcome_observations,
    get_outcome_observation_job,
    run_outcome_observation,
)


class OutcomeJobTests(unittest.TestCase):
    ## Store and retrieve on-demand learning jobs only inside the owner's partition.
    @patch("backend.memory.jobs.put_item")
    @patch("backend.memory.jobs.get_item")
    def test_on_demand_job_is_user_scoped(self, get_item, put_item):
        created = create_outcome_observation_job("user-1")
        saved = put_item.call_args.args[0]
        get_item.return_value = saved

        loaded = get_outcome_observation_job(created["job_id"], "user-1")

        self.assertEqual(saved["pk"], "USER#user-1")
        self.assertEqual(loaded["job_id"], created["job_id"])
        get_item.assert_called_once_with(
            "USER#user-1",
            f"OUTCOME_JOB#{created['job_id']}",
        )

    ## Skip broker calls cleanly when a user has not connected Alpaca.
    @patch(
        "backend.memory.outcome_jobs.get_user_broker_credentials",
        return_value=None,
    )
    def test_observation_requires_connected_broker(self, get_credentials):
        result = run_outcome_observation("user-1")

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "broker_not_connected")

    ## Run the complete refresh from supplied broker data without a scheduler or duplicate client creation.
    @patch(
        "backend.memory.outcome_jobs.get_user_broker_credentials",
        return_value={"broker": "alpaca", "api_key": "key", "secret_key": "secret"},
    )
    @patch("backend.memory.outcome_jobs.import_filled_csp_order_history")
    @patch("backend.memory.outcome_jobs.reconcile_paper_orders")
    @patch("backend.memory.outcome_jobs.capture_current_csp_outcome_snapshots")
    @patch("backend.memory.outcome_jobs.get_option_lifecycle_activities", return_value=[])
    @patch("backend.memory.outcome_jobs.finalize_csp_trade_outcomes")
    @patch("backend.memory.outcome_jobs.analyze_unreviewed_outcomes")
    def test_on_demand_refresh_uses_existing_broker_context(
        self,
        analyze,
        finalize,
        activities,
        capture,
        reconcile,
        import_history,
        get_credentials,
    ):
        import_history.return_value = {
            "imported": 2,
            "skipped_ambiguous_put_sales": 1,
        }
        capture.return_value = {"captured": 1}
        finalize.return_value = {"completed": 1, "unresolved": []}
        analyze.return_value = [{"opening_order_id": "order-1"}]
        trading_client = object()
        positions = [{
            "strategy": "cash-secured put",
            "ticker_symbol": "AAPL",
        }]
        broker_orders = [{"id": "alpaca-order-1"}]

        result = run_outcome_observation(
            "user-1",
            trigger="recommendation_scan",
            include_market_context=False,
            trading_client=trading_client,
            account={"portfolio_value": 100_000, "available_csp_cash": 50_000},
            positions=positions,
            broker_orders=broker_orders,
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["historical_orders_imported"], 2)
        self.assertEqual(result["outcomes_completed"], 1)
        self.assertEqual(result["outcomes_reviewed"], 1)
        import_history.assert_called_once_with("user-1", broker_orders)
        capture.assert_called_once()
        finalize.assert_called_once()

    ## Continue dispatching later users when one asynchronous Lambda invoke fails.
    @patch.dict(os.environ, {"AWS_LAMBDA_FUNCTION_NAME": "helios-api"})
    @patch(
        "backend.memory.outcome_jobs.list_connected_broker_user_ids",
        return_value=["user-1", "user-2"],
    )
    def test_dispatch_isolates_per_user_failure(
        self,
        list_user_ids,
    ):
        lambda_client = Mock()
        lambda_client.invoke.side_effect = [
            RuntimeError("first invoke failed"),
            {"StatusCode": 202},
        ]
        fake_boto3 = SimpleNamespace(
            client=Mock(return_value=lambda_client),
        )

        with (
            patch.dict(sys.modules, {"boto3": fake_boto3}),
            self.assertLogs("backend.memory.outcome_jobs", level="ERROR"),
        ):
            result = dispatch_scheduled_outcome_observations()

        self.assertFalse(result["ok"])
        self.assertEqual(result["users_dispatched"], 1)
        self.assertEqual(result["users_failed"], 1)
        self.assertEqual(lambda_client.invoke.call_count, 2)


if __name__ == "__main__":
    unittest.main()
