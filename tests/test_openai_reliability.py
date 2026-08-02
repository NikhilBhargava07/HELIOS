## Verify safe OpenAI diagnostics and fallback behavior.

import unittest
from unittest.mock import Mock, patch

from backend.market.ai_take import ai_market_take, local_market_take
from backend.openai_client import classify_openai_error


class OpenAIReliabilityTests(unittest.TestCase):
    ## Keep the local fallback usable even when every upstream context source failed.
    def test_market_take_fallback_accepts_empty_context(self):
        take = local_market_take({})

        self.assertEqual(take["review_source"], "local_fallback")
        self.assertEqual(take["market_mood"], "Mixed")
        self.assertEqual(take["csp_stance"], "Wait")

    ## Avoid fabricated trend rankings when only the news feed is available.
    def test_market_take_fallback_handles_news_without_trends(self):
        take = local_market_take({"news": [{"headline": "Current headline"}]})

        self.assertIn("trend rows are not", take["reasoned_take"])
        self.assertNotIn("Recent strength includes ,", take["reasoned_take"])

    ## Translate provider status codes into safe diagnostics instead of exposing response details.
    def test_openai_error_classification_uses_status(self):
        error = RuntimeError("provider detail that should not reach the UI")
        error.status_code = 429

        self.assertEqual(classify_openai_error(error), "rate_limited")

    ## Report a timeout code and return local reasoning when the provider call fails.
    @patch("backend.market.ai_take.get_openai_client")
    def test_market_take_timeout_uses_local_fallback(self, get_client):
        client = Mock()
        client.responses.create.side_effect = TimeoutError("slow provider")
        get_client.return_value = client

        take = ai_market_take({"trends": [], "news": []})

        self.assertEqual(take["review_source"], "local_fallback")
        self.assertEqual(take["ai_error_code"], "timeout")
        self.assertIn("timeout", take["reasoned_take"])


if __name__ == "__main__":
    unittest.main()
