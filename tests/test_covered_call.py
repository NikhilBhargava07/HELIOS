## Verify covered calls: their economics, the cost-basis rule, eligibility, and the placement refusal.
##
## Covered calls reuse the shared option engine, so these tests also confirm that
## the engine scans calls correctly when a strategy supplies call-side economics
## and a strategy-specific rule, and that put-only safeguards still apply to puts.

import unittest
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pandas as pd

from backend.api.services import candidates_to_records, prepare_candidate_for_paper_order
from backend.memory.holdings import build_holdings
from backend.strategy.cash_secured_put import CASH_SECURED_PUT
from backend.strategy.covered_call import (
    COVERED_CALL,
    economics,
    eligible_tickers,
    strike_at_or_above_cost_basis,
)
from backend.strategy.engine.candidates import find_option_candidates
from backend.strategy.recommender import get_recommendation_results


## Build one call snapshot shaped like Alpaca's option-chain response.
def call_snapshot(bid, ask, delta, implied_volatility=0.30, size=5):
    return SimpleNamespace(
        latest_quote=SimpleNamespace(bid_price=bid, ask_price=ask, bid_size=size, ask_size=size),
        greeks=SimpleNamespace(delta=delta),
        implied_volatility=implied_volatility,
    )


## Return an OCC call symbol expiring inside the covered-call DTE window.
def call_symbol(ticker, strike):
    expiration = (date.today() + timedelta(days=35)).strftime("%y%m%d")
    return f"{ticker}{expiration}C{int(strike * 1000):08d}"


class CoveredCallEconomicsTests(unittest.TestCase):
    ## A call is out of the money above the price, and its profit is measured from the real cost basis.
    def test_economics_use_call_side_and_real_cost_basis(self):
        row = economics(strike=200, bid=2.0, current_stock_price=190, dte=35, cost_basis=177)

        self.assertAlmostEqual(row["percentOTM"], (200 - 190) / 190 * 100)
        self.assertEqual(row["costBasis"], 177)
        self.assertEqual(row["breakevenPrice"], 175)
        self.assertEqual(row["premiumIfSoldAtBid"], 200)
        # Called away at 200 on shares that really cost 177: 23 per share plus the premium.
        self.assertEqual(row["maxProfitIfCalledAway"], 2500)
        self.assertAlmostEqual(row["returnOnCashPercent"], 200 / (190 * 100) * 100)

    ## Being called away below cost basis would lock in a loss, so those strikes never reach the model.
    def test_strike_below_cost_basis_is_rejected(self):
        contracts = pd.DataFrame({"strike": [170.0, 177.0, 185.0], "costBasis": [177.0] * 3})

        self.assertEqual(list(strike_at_or_above_cost_basis(contracts)["strike"]), [177.0, 185.0])


class CoveredCallEligibilityTests(unittest.TestCase):
    ## Only an approved ticker with at least one uncovered 100-share lot qualifies.
    def test_eligibility_requires_an_uncovered_lot_of_an_approved_ticker(self):
        holdings = {
            "AAPL": {"uncovered_shares": 100},
            "MSFT": {"uncovered_shares": 50},
            "ZZZZ": {"uncovered_shares": 300},
        }

        self.assertEqual(eligible_tickers({"holdings": holdings}), ["AAPL"])

    ## Premium from a still-held assignment lowers the real cost basis, and open short calls consume shares.
    @patch("backend.memory.holdings.get_completed_trade_outcomes")
    def test_holdings_use_real_cost_basis_and_count_covered_shares(self, outcomes):
        outcomes.return_value = [
            {"ticker_symbol": "AAPL", "assigned": True, "underlying_outcome_pending": True, "opening_credit": 300.0},
            # Already resolved: those shares are gone, so this premium must not count.
            {"ticker_symbol": "MSFT", "assigned": True, "underlying_outcome_pending": False, "opening_credit": 999.0},
        ]
        positions = [
            {"strategy": "stock", "ticker_symbol": "AAPL", "quantity": 200, "average_entry_price": 185.0},
            {"strategy": "call option", "ticker_symbol": "AAPL", "option_type": "call", "signed_quantity": -1},
            {"strategy": "stock", "ticker_symbol": "MSFT", "quantity": 100, "average_entry_price": 400.0},
            # Short stock can never secure a covered call.
            {"strategy": "stock", "ticker_symbol": "TSLA", "quantity": -50, "average_entry_price": 250.0},
        ]

        holdings = build_holdings("user-1", positions)

        self.assertEqual(holdings["AAPL"], {
            "shares": 200,
            "broker_cost_basis": 185.0,
            "cost_basis": (185.0 * 200 - 300.0) / 200,
            "covered_shares": 100,
            "uncovered_shares": 100,
        })
        self.assertEqual(holdings["MSFT"]["cost_basis"], 400.0)
        self.assertNotIn("TSLA", holdings)

    ## An account holding no stock never pays for the outcome lookup.
    @patch("backend.memory.holdings.get_completed_trade_outcomes")
    def test_holdings_skip_outcome_lookup_without_shares(self, outcomes):
        positions = [{"strategy": "cash-secured put", "ticker_symbol": "AAPL", "option_type": "put", "signed_quantity": -1}]

        self.assertEqual(build_holdings("user-1", positions), {})
        outcomes.assert_not_called()


class CoveredCallScanTests(unittest.TestCase):
    ## The shared engine scans calls, needs no cash, and enforces the cost-basis rule inside the pipeline.
    def test_engine_scans_calls_against_cost_basis(self):
        option_data_client = Mock()
        option_data_client.get_option_chain.return_value = {
            # out of the money and above the 195 cost basis: survives
            call_symbol("AAPL", 200): call_snapshot(2.00, 2.10, 0.24),
            # passes every shared threshold, but 192 is below the 195 cost basis
            call_symbol("AAPL", 192): call_snapshot(2.40, 2.50, 0.29),
        }

        candidates = find_option_candidates(
            COVERED_CALL,
            "AAPL",
            available_capital=None,
            current_stock_price=190.0,
            stock_data_client=Mock(),
            option_data_client=option_data_client,
            economics=COVERED_CALL.bind_economics("AAPL", {"holdings": {"AAPL": {"cost_basis": 195.0}}}),
        )

        request = option_data_client.get_option_chain.call_args.args[0]
        self.assertEqual(str(request.type).lower().split(".")[-1], "call")
        self.assertEqual(list(candidates["strike"]), [200.0])
        self.assertNotIn("cashRequired", candidates.columns)

    ## With no qualifying holdings, the rejection names the real requirement instead of "no candidates found".
    def test_missing_holdings_explain_the_requirement(self):
        result = get_recommendation_results(
            COVERED_CALL,
            "user-1",
            total_capital=100_000,
            # At the position cap: covered calls commit no capital, so the cap must not block them.
            current_open_positions=5,
            portfolio_context={"holdings": {}},
            stock_data_client=Mock(),
            option_data_client=Mock(),
        )

        self.assertEqual(result["review"]["summary"], "No tickers currently qualify for a covered call.")
        self.assertIn("at least 100 uncovered shares", result["review"]["risk_note"])

    ## The position cap still limits strategies that commit new capital.
    def test_cash_secured_puts_still_respect_the_position_cap(self):
        result = get_recommendation_results(
            CASH_SECURED_PUT,
            "user-1",
            total_capital=100_000,
            current_open_positions=5,
            stock_data_client=Mock(),
            option_data_client=Mock(),
        )

        self.assertEqual(result["review"]["summary"], "Max open positions reached (5).")


class CoveredCallPlacementTests(unittest.TestCase):
    ## Placement is refused explicitly, before any broker call, rather than by an accidental error later on.
    def test_covered_call_placement_is_refused_before_touching_the_broker(self):
        trading_client = Mock()
        run = {
            "strategy_rules": {"strategy": "covered call"},
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        with self.assertRaisesRegex(ValueError, "can't be placed through HELIOS yet"):
            prepare_candidate_for_paper_order(
                run,
                {"contractSymbol": call_symbol("AAPL", 200)},
                "helios-client-order-id",
                trading_client,
                Mock(),
            )

        trading_client.get_orders.assert_not_called()


class CandidateRecordTests(unittest.TestCase):
    ## Saved records follow each strategy's columns, so a put keeps its fields and a call never needs cashRequired.
    def test_records_follow_each_strategys_columns(self):
        put_row = {column: 1.0 for column in CASH_SECURED_PUT.display_columns}
        put_row.update(tickerSymbol="AAPL", contractSymbol="AAPLP", expiration="2026-12-18")
        call_row = {column: 1.0 for column in COVERED_CALL.display_columns}
        call_row.update(tickerSymbol="AAPL", contractSymbol="AAPLC", expiration="2026-12-18")

        put_keys = set(candidates_to_records(pd.DataFrame([put_row]))[0])
        call_keys = set(candidates_to_records(pd.DataFrame([call_row]))[0])

        # The exact fields a saved put record carried before columns were derived from the strategy.
        self.assertEqual(put_keys, {
            "tickerSymbol", "contractSymbol", "expiration", "DTE", "strike",
            "currentStockPrice", "delta", "ivPercent", "spread",
            "premiumIfSoldAtBid", "cashRequired", "breakevenPrice",
            "returnOnCashPercent", "companyName",
        })
        self.assertIn("costBasis", call_keys)
        self.assertIn("maxProfitIfCalledAway", call_keys)
        self.assertNotIn("cashRequired", call_keys)


if __name__ == "__main__":
    unittest.main()
