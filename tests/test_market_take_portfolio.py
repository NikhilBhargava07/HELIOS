## Verify that the market take reads the whole account, not only the cash-secured puts.
##
## Shares carry their own risk, a short call caps the stock beneath it, and shares with
## no call sold against them are the next step of a wheel. All three have to reach the
## model, survive the compaction that trims the prompt, and still be described when the
## model is unavailable.

import unittest

from backend.market.ai_take import MARKET_TAKE_SCHEMA, local_market_take
from backend.market.prompt_context import compact_portfolio_context

TRENDS = [
    {"ticker": "AAPL", "5d": 2.4},
    {"ticker": "MSFT", "5d": -1.1},
]


## Build a portfolio holding shares, one covered call, and one cash-secured put.
def portfolio():
    return {
        "capital": {"total_capital": 100_000, "committed_capital": 18_000},
        "open_csp_positions": [
            {"ticker_symbol": "MSFT", "contract_symbol": "MSFT261218P00400000",
             "option_type": "put", "strike": 400.0, "quantity": 1, "cash_required": 40_000},
        ],
        "covered_call_positions": [
            {"ticker_symbol": "AAPL", "contract_symbol": "AAPL261218C00210000",
             "option_type": "call", "strike": 210.0, "quantity": 1},
        ],
        "share_positions": [
            {"ticker_symbol": "AAPL", "quantity": 200, "average_entry_price": 200.0,
             "market_value": 46_430.0, "unrealized_pnl": 6_430.0},
            {"ticker_symbol": "NVDA", "quantity": 150, "average_entry_price": 118.0,
             "market_value": 18_210.0, "unrealized_pnl": 510.0},
        ],
        "holdings": {
            "AAPL": {"shares": 200, "cost_basis": 197.0, "covered_shares": 100, "uncovered_shares": 100},
            "NVDA": {"shares": 150, "cost_basis": 118.0, "covered_shares": 0, "uncovered_shares": 150},
        },
        "position_source": "alpaca",
    }


class MarketTakeContextTests(unittest.TestCase):
    ## Every kind of position survives compaction in its own named group.
    def test_compaction_keeps_each_position_group(self):
        compacted = compact_portfolio_context(portfolio())

        self.assertEqual(len(compacted["open_csp_positions"]), 1)
        self.assertEqual(len(compacted["covered_call_positions"]), 1)
        self.assertEqual(len(compacted["share_positions"]), 2)
        # The real cost of the shares only exists here, and it decides whether a call locks in a gain.
        self.assertEqual(compacted["holdings"]["AAPL"]["cost_basis"], 197.0)

    ## A short call is labelled as one, so it can never be read as a put.
    def test_compacted_positions_name_their_contract_type(self):
        compacted = compact_portfolio_context(portfolio())

        self.assertEqual(compacted["covered_call_positions"][0]["option_type"], "call")
        self.assertEqual(compacted["open_csp_positions"][0]["option_type"], "put")

    ## An account with nothing in it compacts to empty groups rather than missing keys.
    def test_empty_portfolio_still_has_every_group(self):
        compacted = compact_portfolio_context({})

        self.assertEqual(compacted["covered_call_positions"], [])
        self.assertEqual(compacted["share_positions"], [])
        self.assertEqual(compacted["holdings"], {})


class MarketTakeShapeTests(unittest.TestCase):
    ## The model is required to speak to the call side and the shares, not just the puts.
    def test_schema_requires_a_take_on_every_part_of_the_account(self):
        for field in ("csp_take", "covered_call_take", "stock_take", "portfolio_take"):
            self.assertIn(field, MARKET_TAKE_SCHEMA["required"])
            self.assertIn(field, MARKET_TAKE_SCHEMA["properties"])


class MarketTakeFallbackTests(unittest.TestCase):
    ## Without the model, the fallback still states what the account actually holds.
    def test_fallback_describes_calls_shares_and_free_lots(self):
        take = local_market_take({"trends": TRENDS, "portfolio": portfolio()})

        self.assertIn("AAPL", take["covered_call_take"])
        # 100 AAPL shares and 150 NVDA shares have no call against them.
        self.assertIn("AAPL", take["covered_call_take"].split("free to cover")[-1])
        self.assertIn("NVDA", take["covered_call_take"])
        self.assertIn("AAPL", take["stock_take"])
        self.assertIn("NVDA", take["stock_take"])

    ## An account with no calls and no shares says so plainly instead of inventing activity.
    def test_fallback_states_an_empty_call_and_share_side(self):
        take = local_market_take({"trends": TRENDS, "portfolio": {"open_csp_positions": []}})

        self.assertIn("No covered calls", take["covered_call_take"])
        self.assertIn("No shares", take["stock_take"])

    ## Even with no context at all, every section the page renders gets an answer.
    def test_empty_context_still_answers_every_section(self):
        take = local_market_take({})

        for field in ("csp_take", "covered_call_take", "stock_take", "portfolio_take"):
            self.assertTrue(take[field], f"{field} was empty")


if __name__ == "__main__":
    unittest.main()
