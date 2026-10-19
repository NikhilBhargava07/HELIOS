## Verify ownership checks when recommendation runs are loaded by id, and that a stored
## run stays small enough for DynamoDB to accept it.

import json
import unittest
from unittest.mock import patch

from backend.memory.recommendations import get_recommendation_run, save_recommendation_run


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


class StoredRunSizeTests(unittest.TestCase):
    ## Retrieved memory is compacted before it is stored, not written in full.
    ##
    ## The raw context grows with every recorded decision. Stored whole it reached 388KB of a
    ## 450KB item and crossed DynamoDB's 400KB ceiling, which made a scan fail on its own save
    ## with an error naming neither the field nor the strategy. The prompt builders had always
    ## compacted it; only the stored copy did not.
    @patch("backend.memory.recommendations.put_items")
    @patch("backend.memory.recommendations.put_item")
    def test_memory_context_is_not_stored_raw(self, put_item, _put_items):
        bulky = {
            "relevant_episodes": [
                {"summary": "an old decision and everything recorded about it " * 40,
                 "contract_symbol": f"AAPL2609{index:02d}P00200000"}
                for index in range(1, 60)
            ],
        }

        save_recommendation_run("user-a", [], {"decision": "needs_review"}, memory_context=bulky)

        stored = put_item.call_args.args[0]["memory_context"]
        raw_size = len(json.dumps(bulky).encode("utf-8"))
        stored_size = len(json.dumps(stored, default=str).encode("utf-8"))

        self.assertLess(stored_size, raw_size / 2, "memory context was stored close to raw")
        self.assertLess(stored_size, 100 * 1024, "a stored run must stay well under DynamoDB's 400KB limit")

    ## A run that is approaching the item ceiling says so while it is still only large.
    @patch("backend.memory.dynamodb_store.get_table")
    def test_an_oversized_item_is_reported_before_it_fails(self, _table):
        from backend.memory.dynamodb_store import put_item as store_item

        with self.assertLogs("backend.memory.dynamodb_store", level="WARNING") as logs:
            store_item({"pk": "RUN#1", "sk": "META", "item_type": "recommendation_run",
                        "memory_context": "x" * (320 * 1024)})

        self.assertIn("memory_context", logs.output[0])
        self.assertIn("recommendation_run", logs.output[0])
