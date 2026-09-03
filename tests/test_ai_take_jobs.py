## Verify that asynchronous market-take jobs remain isolated by authenticated user.

import unittest
from unittest.mock import patch

from backend.market.ai_take_jobs import get_market_take_job


class MarketTakeJobOwnershipTests(unittest.TestCase):
    ## Read a job from the requesting user's partition rather than a shared global key.
    @patch("backend.memory.jobs.get_item")
    def test_job_lookup_uses_user_partition(self, get_item):
        get_item.return_value = {
            "job_id": "job-1",
            "status": "pending",
        }

        result = get_market_take_job("job-1", "user-a")

        self.assertEqual(result["job_id"], "job-1")
        get_item.assert_called_once_with(
            "USER#user-a",
            "AI_TAKE_JOB#job-1",
        )

    ## Treat a missing item in the user's partition as an unavailable job.
    @patch("backend.memory.jobs.get_item", return_value=None)
    def test_missing_user_job_returns_none(self, _get_item):
        self.assertIsNone(get_market_take_job("job-1", "user-b"))


if __name__ == "__main__":
    unittest.main()
