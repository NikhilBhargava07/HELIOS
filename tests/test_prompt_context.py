## Verify that historical memory is bounded before it is sent to OpenAI.

import unittest

from backend.market.prompt_context import (
    compact_market_take_context,
    compact_memory_context,
)


class PromptContextTests(unittest.TestCase):
    ## Remove recursively saved market evidence from old recommendation episodes.
    def test_memory_compaction_drops_nested_market_context(self):
        memory = {
            "relevant_episodes": [{
                "recommended_at": "2026-08-01T12:00:00+00:00",
                "ticker_symbol": "AAPL",
                "contract_symbol": "AAPL260821P00200000",
                "candidate": {
                    "tickerSymbol": "AAPL",
                    "contractSymbol": "AAPL260821P00200000",
                    "strike": 200,
                    "unused_ui_field": "remove me",
                },
                "agent_review": {
                    "decision": "approve",
                    "summary": "A" * 500,
                },
                "market_context": {
                    "news": [{"headline": "Old nested evidence"}],
                },
                "completed_outcome": {
                    "resolution_type": "bought_to_close",
                    "option_realized_pnl": 125,
                    "premium_retained_percent": 62.5,
                    "interpretation": "Measured closing result.",
                    "evidence": {"large": "broker payload"},
                },
            }],
        }

        compacted = compact_memory_context(memory)
        episode = compacted["relevant_episodes"][0]

        self.assertNotIn("market_context", episode)
        self.assertNotIn("unused_ui_field", episode["candidate"])
        self.assertLessEqual(len(episode["agent_review"]["summary"]), 283)
        self.assertEqual(
            episode["completed_outcome"]["option_realized_pnl"],
            125,
        )
        self.assertNotIn("evidence", episode["completed_outcome"])

    ## Keep current recommendation facts while excluding its already-saved prompt context.
    def test_market_take_compaction_avoids_reembedding_old_context(self):
        context = {
            "trends": [{"ticker": "SPY", "5d": 1.5}],
            "news": [{"headline": "Current headline", "url": "https://example.test"}],
            "latest_recommendation": {
                "id": "run-1",
                "candidates": [{
                    "tickerSymbol": "AAPL",
                    "contractSymbol": "AAPL260821P00200000",
                    "strike": 200,
                }],
                "memory_context": {"large": "old prompt"},
                "market_context": {"news": [{"headline": "old"}]},
            },
        }

        compacted = compact_market_take_context(context)
        recommendation = compacted["latest_recommendation"]

        self.assertEqual(recommendation["id"], "run-1")
        self.assertEqual(recommendation["candidates"][0]["tickerSymbol"], "AAPL")
        self.assertNotIn("memory_context", recommendation)
        self.assertNotIn("market_context", recommendation)
        self.assertNotIn("url", compacted["news"][0])


if __name__ == "__main__":
    unittest.main()
