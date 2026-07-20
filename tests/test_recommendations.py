## Verify ownership checks when recommendation runs are loaded by id.

import unittest
from unittest.mock import patch

from backend.memory.recommendations import get_recommendation_run


class RecommendationOwnershipTests(unittest.TestCase):
    ## Refuse a globally addressable run id when it belongs to another user.
    @patch("backend.memory.recommendations.query_items")
    @patch("backend.memory.recommendations.get_item")
    def test_cross_user_run_is_hidden(self, get_item, query_items):
        get_item.return_value = {"id": "run-1", "user_id": "user-a"}

        result = get_recommendation_run("user-b", "run-1")

        self.assertIsNone(result)
        query_items.assert_not_called()

    ## Reconstruct candidates when the stored run owner matches the requester.
    @patch("backend.memory.recommendations.query_items")
    @patch("backend.memory.recommendations.get_item")
    def test_owner_can_load_run(self, get_item, query_items):
        get_item.return_value = {
            "id": "run-1",
            "user_id": "user-a",
            "created_at": "2026-07-20T00:00:00+00:00",
        }
        query_items.return_value = [{"candidate": {"contractSymbol": "AAPL-PUT-1"}}]

        result = get_recommendation_run("user-a", "run-1")

        self.assertEqual(result["id"], "run-1")
        self.assertEqual(result["candidates"][0]["contractSymbol"], "AAPL-PUT-1")


if __name__ == "__main__":
    unittest.main()
