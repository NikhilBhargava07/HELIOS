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
## Both pay the same premium; only the size of the move the market expects differs.
def matched_pair(quiet_iv=25.0, loud_iv=70.0):
    return pd.DataFrame([
        {"contractSymbol": "QUIET", "delta": -0.25, "ivPercent": quiet_iv, "spread": 0.10,
         "bid": 2.00, "DTE": 37, "returnOnCashPercent": 2.0, "percentOTM": 8.0},
        {"contractSymbol": "LOUD", "delta": -0.25, "ivPercent": loud_iv, "spread": 0.10,
         "bid": 2.00, "DTE": 37, "returnOnCashPercent": 2.0, "percentOTM": 8.0},
    ])


## Score a frame and return each contract's score by symbol.
def scores_for(contracts, target_delta=-0.25):
    return add_recommendation_score(contracts, target_delta).set_index("contractSymbol")["score"]


class RankingTests(unittest.TestCase):
    ## Same premium for a smaller expected move is the better trade, and now ranks that way.
    ##
    ## The delta filter pins both to about the same chance of assignment, so the volatile
    ## one is not likelier to be assigned; it simply falls further when it is.
    def test_the_same_premium_for_less_expected_movement_ranks_higher(self):
        scores = scores_for(matched_pair())

        self.assertGreater(scores["QUIET"], scores["LOUD"])

    ## Paying more for the same expected move still wins, since return is still the reward.
    def test_stronger_return_still_wins_at_equal_volatility(self):
        contracts = matched_pair(quiet_iv=40.0, loud_iv=40.0)
        contracts.loc[contracts["contractSymbol"] == "QUIET", "returnOnCashPercent"] = 3.0

        scores = scores_for(contracts)

        self.assertGreater(scores["QUIET"], scores["LOUD"])

    ## More room before the strike wins when reward and volatility match.
    def test_more_cushion_wins_when_everything_else_matches(self):
        contracts = matched_pair(quiet_iv=40.0, loud_iv=40.0)
        contracts.loc[contracts["contractSymbol"] == "QUIET", "percentOTM"] = 12.0

        scores = scores_for(contracts)

        self.assertGreater(scores["QUIET"], scores["LOUD"])

    ## Drifting away from the target delta is still penalised harder than anything else rewards.
    def test_missing_target_delta_still_outweighs_a_better_return(self):
        contracts = matched_pair(quiet_iv=40.0, loud_iv=40.0)
        contracts.loc[contracts["contractSymbol"] == "LOUD", "delta"] = -0.40
        contracts.loc[contracts["contractSymbol"] == "LOUD", "returnOnCashPercent"] = 3.0

        scores = scores_for(contracts)

        self.assertGreater(scores["QUIET"], scores["LOUD"])

    ## A broken volatility reading cannot divide a score to the top of the list.
    def test_a_zero_volatility_reading_cannot_dominate(self):
        contracts = matched_pair(quiet_iv=0.0, loud_iv=40.0)

        scores = scores_for(contracts)

        self.assertTrue(pd.notna(scores["QUIET"]))
        self.assertLess(scores["QUIET"], 1000)


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
