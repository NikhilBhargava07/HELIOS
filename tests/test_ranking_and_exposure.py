## Verify the two rules that stop one ticker dominating every scan.
##
## HELIOS recommended the same handful of names because the ranking paid a bonus for
## implied volatility that the return already contained, and because nothing stopped
## it offering a put on a ticker the account was already exposed to. These tests pin
## both down: volatility no longer buys rank on its own, and a name already held is
## not offered again.

import unittest

import pandas as pd

from backend.strategy.cash_secured_put import eligible_tickers
from backend.strategy.engine.candidates import add_recommendation_score


## Build two contracts identical in every ranked term except implied volatility.
def matched_pair(quiet_iv=25.0, loud_iv=70.0):
    return pd.DataFrame([
        {"contractSymbol": "QUIET", "delta": -0.25, "ivPercent": quiet_iv, "spread": 0.10,
         "bid": 2.00, "annualizedReturnPercent": 30.0, "percentOTM": 8.0},
        {"contractSymbol": "LOUD", "delta": -0.25, "ivPercent": loud_iv, "spread": 0.10,
         "bid": 2.00, "annualizedReturnPercent": 30.0, "percentOTM": 8.0},
    ])


class RankingTests(unittest.TestCase):
    ## Two contracts paying the same return rank the same, however differently the market prices their risk.
    def test_volatility_alone_no_longer_buys_rank(self):
        scored = add_recommendation_score(matched_pair(), target_delta=-0.25)

        quiet, loud = scored.set_index("contractSymbol")["score"]["QUIET"], scored.set_index("contractSymbol")["score"]["LOUD"]
        self.assertEqual(quiet, loud)

    ## Return still decides, since that is the actual reward for selling the contract.
    def test_stronger_return_still_wins(self):
        contracts = matched_pair()
        contracts.loc[contracts["contractSymbol"] == "QUIET", "annualizedReturnPercent"] = 40.0

        scored = add_recommendation_score(contracts, target_delta=-0.25).set_index("contractSymbol")

        self.assertGreater(scored["score"]["QUIET"], scored["score"]["LOUD"])

    ## Drifting away from the target delta is still penalised harder than anything else rewards.
    def test_missing_target_delta_still_outweighs_a_better_return(self):
        contracts = matched_pair()
        contracts.loc[contracts["contractSymbol"] == "LOUD", "delta"] = -0.40
        contracts.loc[contracts["contractSymbol"] == "LOUD", "annualizedReturnPercent"] = 40.0

        scored = add_recommendation_score(contracts, target_delta=-0.25).set_index("contractSymbol")

        self.assertGreater(scored["score"]["QUIET"], scored["score"]["LOUD"])


class ExposureTests(unittest.TestCase):
    ## An account with nothing in it can be offered the whole approved universe.
    def test_an_empty_account_sees_every_approved_ticker(self):
        self.assertIn("ORCL", eligible_tickers({}))
        self.assertIn("ORCL", eligible_tickers(None))

    ## A ticker with an open put is not offered the same obligation twice.
    def test_a_ticker_with_an_open_put_is_not_offered_again(self):
        tickers = eligible_tickers({
            "open_csp_positions": [{"ticker_symbol": "ORCL", "contract_symbol": "ORCL261016P00135000"}],
        })

        self.assertNotIn("ORCL", tickers)
        self.assertIn("AAPL", tickers)

    ## Shares already held mean assignment would add to a position rather than start one.
    def test_a_ticker_whose_shares_are_held_is_not_offered(self):
        tickers = eligible_tickers({"holdings": {"ORCL": {"shares": 100, "cost_basis": 130.0}}})

        self.assertNotIn("ORCL", tickers)

    ## A holding that has been fully sold no longer blocks the ticker.
    def test_a_closed_holding_does_not_block_the_ticker(self):
        tickers = eligible_tickers({"holdings": {"ORCL": {"shares": 0, "cost_basis": 130.0}}})

        self.assertIn("ORCL", tickers)

    ## Both kinds of exposure are excluded together, and the rest of the universe survives.
    def test_puts_and_shares_are_excluded_together(self):
        tickers = eligible_tickers({
            "open_csp_positions": [{"ticker_symbol": "INTC"}],
            "holdings": {"ORCL": {"shares": 200}, "NKE": {"shares": 100}},
        })

        for held in ("INTC", "ORCL", "NKE"):
            self.assertNotIn(held, tickers)
        self.assertGreater(len(tickers), 40)


if __name__ == "__main__":
    unittest.main()
