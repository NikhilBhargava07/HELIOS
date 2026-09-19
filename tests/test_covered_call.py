## Verify covered calls: their economics, the cost-basis rule, eligibility, placement, and saved records.
##
## Covered calls reuse the shared option engine and the shared placement gate, so
## these tests also confirm that the engine scans calls correctly when a strategy
## supplies call-side economics and a strategy-specific rule, that an order is only
## sent when live broker state proves the shares are there, and that put-only
## safeguards still apply to puts.

import unittest
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pandas as pd

from backend.api.services import candidates_to_records, prepare_candidate_for_paper_order
from backend.memory.holdings import build_holdings
from backend.memory.recommendations import save_recommendation_run
from backend.memory.trades import record_user_decision
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


## Build a live option quote shaped like Alpaca's latest-quote response.
def latest_quote(bid, ask, size=5):
    return SimpleNamespace(model_dump=lambda mode="json": {
        "bid_price": str(bid),
        "ask_price": str(ask),
        "bid_size": str(size),
        "ask_size": str(size),
        "timestamp": "2026-09-18T15:30:00Z",
    })


## Run the placement gate for one covered call against a mocked broker account.
def place_covered_call(positions, candidate=None, broker_orders=(), outcomes=()):
    contract_symbol = call_symbol("AAPL", 200)
    candidate = candidate or {
        "contractSymbol": contract_symbol,
        "tickerSymbol": "AAPL",
        "strike": 200.0,
        "currentStockPrice": 190.0,
        "DTE": 35,
        "costBasis": 177.0,
        "breakevenPrice": 175.0,
        "premiumIfSoldAtBid": 200.0,
        "maxProfitIfCalledAway": 2500.0,
        "returnOnCashPercent": 1.05,
    }
    option_data_client = Mock()
    option_data_client.get_option_latest_quote.return_value = {contract_symbol: latest_quote(2.50, 2.60)}

    with patch("backend.api.services.get_paper_orders", return_value=list(broker_orders)), \
         patch("backend.api.services.get_paper_account_summary", return_value={"available_csp_cash": 0.0}), \
         patch("backend.api.services.get_paper_positions", return_value=positions), \
         patch("backend.memory.holdings.get_completed_trade_outcomes", return_value=list(outcomes)):
        return prepare_candidate_for_paper_order(
            "user-1",
            {
                "strategy_rules": {"strategy": "covered call"},
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
            candidate,
            "helios-client-order-id",
            Mock(),
            option_data_client,
        )


class CoveredCallPlacementTests(unittest.TestCase):
    ## Shares held now, not shares seen during the scan, decide whether a call is covered.
    def test_placement_requires_shares_in_the_account(self):
        with self.assertRaisesRegex(ValueError, "holds no AAPL shares"):
            place_covered_call(positions=[])

    ## Shares already committed to an open short call cannot cover a second one.
    def test_placement_rejects_shares_committed_to_an_open_call(self):
        positions = [
            {"strategy": "stock", "ticker_symbol": "AAPL", "quantity": 100, "average_entry_price": 177.0},
            {"strategy": "call option", "ticker_symbol": "AAPL", "option_type": "call", "signed_quantity": -1},
        ]

        with self.assertRaisesRegex(ValueError, "only 0 of the 100 shares held are free"):
            place_covered_call(positions=positions)

    ## An unfilled sell order commits its shares too, so the same lot cannot back two orders.
    def test_placement_rejects_shares_committed_to_a_pending_order(self):
        positions = [
            {"strategy": "stock", "ticker_symbol": "AAPL", "quantity": 100, "average_entry_price": 177.0},
        ]
        pending = [{"symbol": call_symbol("AAPL", 210), "side": "sell", "status": "accepted", "qty": "1"}]

        with self.assertRaisesRegex(ValueError, "shares that are not already committed"):
            place_covered_call(positions=positions, broker_orders=pending)

    ## Buying more shares raises the real cost basis, so a strike that passed the scan can stop being safe.
    def test_placement_rechecks_the_strike_against_live_cost_basis(self):
        positions = [
            {"strategy": "stock", "ticker_symbol": "AAPL", "quantity": 100, "average_entry_price": 205.0},
        ]

        with self.assertRaisesRegex(ValueError, r"\$200.00 strike is below the \$205.00"):
            place_covered_call(positions=positions)

    ## A covered call with free shares is repriced from the live quote against the real cost basis, with no cash check.
    def test_covered_shares_allow_placement_and_reprice_from_cost_basis(self):
        positions = [
            {"strategy": "stock", "ticker_symbol": "AAPL", "quantity": 100, "average_entry_price": 180.0},
        ]
        # A put assigned at 180 collected 300 in premium, so the shares really cost 177.
        outcomes = [{
            "ticker_symbol": "AAPL",
            "assigned": True,
            "underlying_outcome_pending": True,
            "opening_credit": 300.0,
        }]

        placement = place_covered_call(positions=positions, outcomes=outcomes)
        candidate = placement["candidate"]

        self.assertEqual(placement["strategy"].key, "covered_call")
        self.assertEqual(candidate["premiumIfSoldAtBid"], 250.0)
        self.assertEqual(candidate["costBasis"], 177.0)
        self.assertEqual(candidate["breakevenPrice"], 177.0 - 2.50)
        self.assertEqual(candidate["maxProfitIfCalledAway"], (200.0 - 177.0) * 100 + 250.0)
        self.assertNotIn("cashRequired", candidate)


class CoveredCallOrderRecordTests(unittest.TestCase):
    ## A placed covered call is stored as one: secured by shares, so it commits no cash and keeps its cost basis.
    @patch("backend.memory.trades.put_item")
    @patch("backend.memory.trades.get_item", return_value=None)
    @patch("backend.memory.trades.get_recommendation_run")
    def test_placed_covered_call_records_shares_not_cash(self, get_run, _get_item, put_item):
        candidate = {
            "contractSymbol": call_symbol("AAPL", 200),
            "tickerSymbol": "AAPL",
            "expiration": "2026-12-18",
            "strike": 200.0,
            "costBasis": 177.0,
            "breakevenPrice": 174.5,
            "premiumIfSoldAtBid": 250.0,
            "returnOnCashPercent": 1.3,
        }
        get_run.return_value = {
            "candidates": [candidate],
            "agent_review": {"selected_contract": candidate["contractSymbol"], "decision": "approve"},
            "strategy_rules": {"strategy": "covered call"},
        }

        record_user_decision(
            "user-1",
            "run-1",
            candidate["contractSymbol"],
            "place_paper_order",
            alpaca_order={"id": "alpaca-1", "status": "filled", "filled_qty": "1", "filled_avg_price": "2.40"},
            strategy=COVERED_CALL,
        )

        order = next(item for item in put_item.call_args_list if item.args[0].get("item_type") == "paper_order").args[0]
        self.assertEqual(order["strategy"], "covered call")
        self.assertEqual(order["cash_required"], 0)
        self.assertEqual(order["cost_basis"], 177.0)
        # Filled at 2.40 against shares that cost 177: breakeven falls from the basis, not the strike.
        self.assertEqual(order["premium_received"], 240.0)
        self.assertEqual(order["breakeven_price"], 174.6)

    ## An order can never be saved without the strategy that says how it is secured.
    @patch("backend.memory.trades.put_item")
    @patch("backend.memory.trades.get_item", return_value=None)
    @patch("backend.memory.trades.get_recommendation_run")
    def test_placed_order_without_a_strategy_is_refused(self, get_run, _get_item, _put_item):
        candidate = {"contractSymbol": "AAPL260821P00200000", "tickerSymbol": "AAPL"}
        get_run.return_value = {
            "candidates": [candidate],
            "agent_review": {"selected_contract": None, "decision": "approve"},
        }

        with self.assertRaisesRegex(ValueError, "must record the strategy"):
            record_user_decision("user-1", "run-1", candidate["contractSymbol"], "place_paper_order")


class CandidateRecordTests(unittest.TestCase):
    ## A saved run keeps the columns its strategy produced, so a covered call is still priceable when placed.
    @patch("backend.memory.recommendations.put_items")
    @patch("backend.memory.recommendations.put_item")
    def test_saved_run_keeps_strategy_specific_columns(self, _put_item, put_items):
        candidate = {
            "tickerSymbol": "AAPL",
            "contractSymbol": call_symbol("AAPL", 200),
            "expiration": "2026-12-18",
            "DTE": 35,
            "strike": 200.0,
            "costBasis": 177.0,
            "maxProfitIfCalledAway": 2500.0,
        }

        run = save_recommendation_run("user-1", [candidate], {"decision": "approve"})

        stored = next(
            item["candidate"] for item in put_items.call_args.args[0]
            if item.get("item_type") == "recommendation_candidate"
        )
        self.assertEqual(stored["costBasis"], 177.0)
        self.assertEqual(stored["maxProfitIfCalledAway"], 2500.0)
        self.assertEqual(run["candidates"][0]["costBasis"], 177.0)


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
