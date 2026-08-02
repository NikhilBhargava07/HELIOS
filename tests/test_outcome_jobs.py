## Verify scheduled CSP observation dispatch behavior.

import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from backend.memory.outcome_jobs import (
    dispatch_scheduled_outcome_observations,
    run_outcome_observation,
)


class OutcomeJobTests(unittest.TestCase):
    ## Skip broker calls cleanly when a user has not connected Alpaca.
    @patch(
        "backend.memory.outcome_jobs.get_user_broker_credentials",
        return_value=None,
    )
    def test_observation_requires_connected_broker(self, get_credentials):
        result = run_outcome_observation("user-1")

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "broker_not_connected")

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
