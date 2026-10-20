## Verify the one account-wide capital rule: a share of the balance is never committed.
##
## HELIOS used to give cash-secured puts a fixed 70% of the account, which decided how much
## of someone's money went into one strategy. That is the user's call. What remains is a
## liquidity floor, so an assignment or a drawdown does not force a sale at the worst moment.

import unittest
from unittest.mock import Mock

from backend.capital import investable_capacity
from backend.config import CASH_BACKED_STRATEGY_KEYS, LIQUID_RESERVE_PERCENT
from backend.strategy.recommender import available_strategy_capital


class LiquidReserveTests(unittest.TestCase):
    ## The reserve is held back before anything is called available.
    def test_the_reserve_is_withheld_from_the_balance(self):
        reserve, investable, available = investable_capacity(100_000, 0.10, 0)

        self.assertEqual(reserve, 10_000)
        self.assertEqual(investable, 90_000)
        self.assertEqual(available, 90_000)

    ## What is already committed comes out of the investable share, not out of the reserve.
    def test_committed_capital_reduces_only_what_is_investable(self):
        reserve, investable, available = investable_capacity(100_000, 0.10, 25_000)

        self.assertEqual(reserve, 10_000)
        self.assertEqual(investable, 90_000)
        self.assertEqual(available, 65_000)

    ## An over-committed account reports no capacity rather than a negative one.
    def test_an_over_committed_account_reports_nothing_available(self):
        self.assertEqual(investable_capacity(10_000, 0.10, 50_000)[2], 0)

    ## A missing or zero balance must not produce a negative reserve.
    def test_an_empty_account_is_handled(self):
        self.assertEqual(investable_capacity(0, 0.10, 0), (0, 0, 0))
        self.assertEqual(investable_capacity(None, 0.10, 0), (0, 0, 0))

    ## The default sits inside the five-to-ten percent band this rule was asked for.
    def test_the_configured_reserve_is_within_the_intended_band(self):
        self.assertGreaterEqual(LIQUID_RESERVE_PERCENT, 0.05)
        self.assertLessEqual(LIQUID_RESERVE_PERCENT, 0.10)


class StrategyCapitalTests(unittest.TestCase):
    ## A cash-backed strategy is limited by the reserve and by nothing strategy-specific.
    def test_a_cash_backed_strategy_may_use_everything_outside_the_reserve(self):
        strategy = Mock(key="cash_secured_put")

        available = available_strategy_capital(strategy, 100_000, 0)

        self.assertEqual(available, 100_000 * (1 - LIQUID_RESERVE_PERCENT))

    ## The broker's own limit still wins when it is the stricter of the two.
    def test_the_broker_limit_still_applies(self):
        strategy = Mock(key="cash_secured_put")

        available = available_strategy_capital(
            strategy, 100_000, 0, external_available_capital=12_000,
        )

        self.assertEqual(available, 12_000)

    ## A covered call is secured by shares already owned, so capital never limits it.
    def test_a_strategy_backed_by_shares_has_no_capital_limit(self):
        self.assertNotIn("covered_call", CASH_BACKED_STRATEGY_KEYS)
        self.assertIsNone(available_strategy_capital(Mock(key="covered_call"), 100_000, 0))
        self.assertIsNone(available_strategy_capital(Mock(key="equity"), 100_000, 0))


if __name__ == "__main__":
    unittest.main()
