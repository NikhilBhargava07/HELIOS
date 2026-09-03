## Verify that outcome learning counts independent contracts rather than refresh snapshots.

import unittest
from unittest.mock import patch

from backend.memory.learning_user import build_user_profile, get_outcome_patterns


class OutcomePatternTests(unittest.TestCase):
    ## Confirm that two observations of one contract still count as one sample.
    def test_patterns_use_distinct_contracts(self):
        snapshots = [
            self._snapshot("AAPL-PUT-1", "2026-07-03T12:00:00+00:00"),
            self._snapshot("AAPL-PUT-1", "2026-07-02T12:00:00+00:00"),
            self._snapshot("AAPL-PUT-2", "2026-07-01T12:00:00+00:00"),
        ]

        with patch(
            "backend.memory.learning_user.get_recent_outcome_snapshots",
            return_value=snapshots,
        ), patch(
            "backend.memory.learning_user.get_completed_trade_outcomes",
            return_value=[],
        ):
            result = get_outcome_patterns(
                "user-1",
                ticker_symbols=["AAPL"],
                minimum_sample_size=2,
            )

        self.assertEqual(len(result["patterns"]), 1)
        self.assertEqual(result["patterns"][0]["sample_size"], 2)
        self.assertEqual(len(result["recent_lessons"]), 3)

    ## Use explicit feedback immediately while keeping measured assignment outcomes separate.
    @patch("backend.memory.learning_user.get_trade_feedback")
    @patch("backend.memory.learning_user.get_completed_trade_outcomes")
    @patch("backend.memory.learning_user.query_items", return_value=[])
    def test_profile_separates_feedback_from_economics(
        self,
        decisions,
        completed_outcomes,
        feedback,
    ):
        completed_outcomes.return_value = [{
            "assigned": True,
            "option_realized_pnl": 200,
            "premium_retained_percent": 100,
        }]
        feedback.return_value = [{
            "satisfaction": "mixed",
            "would_repeat": False,
            "assignment_preference": "welcome",
            "reason_tags": ["timing", "assignment"],
        }]

        result = build_user_profile("user-1")["profile"]

        self.assertEqual(result["outcome_preferences"]["assignment_rate"], 1)
        self.assertEqual(
            result["outcome_preferences"]["assignment_tolerance"],
            "welcomes_assignment",
        )
        self.assertEqual(result["outcome_preferences"]["would_repeat_rate"], 0)
        self.assertEqual(result["outcome_preferences"]["total_option_realized_pnl"], 200)

    ## Build one realistic stored observation for the aggregation test.
    @staticmethod
    def _snapshot(contract_symbol, observed_at):
        return {
            "observed_at": observed_at,
            "summary": "Position remains profitable without assignment.",
            "snapshot": {
                "ticker_symbol": "AAPL",
                "contract_symbol": contract_symbol,
                "lesson_type": "premium_retention",
                "financial_status": "profitable",
                "assignment_status": "not_assigned",
            },
        }


if __name__ == "__main__":
    unittest.main()
