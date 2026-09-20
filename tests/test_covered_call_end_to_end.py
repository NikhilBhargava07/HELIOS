## Walk one covered call through every stage HELIOS owns, on a fake account.
##
## The unit tests cover each stage on its own. This one runs a whole wheel
## through the real code paths in order: a put is assigned, the shares it
## delivered are scanned for a covered call, the call is placed against live
## broker state, and being exercised settles both the call and the assignment
## that produced the shares. Nothing here reaches Alpaca, OpenAI, or DynamoDB;
## storage is an in-memory table and the broker is a fake holding 100 shares.

import unittest
from contextlib import ExitStack
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock, patch

from backend.api.services import candidates_to_records, prepare_candidate_for_paper_order
from backend.memory.holdings import build_holdings
from backend.memory.outcomes import finalize_trade_outcomes
from backend.memory.recommendations import save_recommendation_run
from backend.memory.trades import record_user_decision
from backend.strategy.covered_call import COVERED_CALL
from backend.strategy.recommender import get_recommendation_results

USER_ID = "user-e2e"
TICKER = "AAPL"
STRIKE = 210.0
SHARE_PRICE = 200.0
# A put assigned at 200 that collected 300 in premium leaves shares that really cost 197.
BROKER_COST_BASIS = 200.0
ASSIGNMENT_PREMIUM = 300.0
REAL_COST_BASIS = 197.0

# Modules that imported the DynamoDB helpers directly, so each name is patched where it is used.
STORE_USERS = (
    "backend.memory.recommendations",
    "backend.memory.trades",
    "backend.memory.outcomes",
)


## Stand in for the single DynamoDB table with a plain dictionary.
class FakeTable:
    def __init__(self):
        self.items = {}

    def put_item(self, item):
        self.items[(item["pk"], item["sk"])] = dict(item)

    def put_items(self, items):
        for item in items:
            self.put_item(item)

    def get_item(self, pk, sk):
        return self.items.get((pk, sk))

    def query_items(self, pk, prefix, limit=100, scan_forward=True):
        rows = sorted(
            (item for (item_pk, sk), item in self.items.items() if item_pk == pk and sk.startswith(prefix)),
            key=lambda item: item["sk"],
            reverse=not scan_forward,
        )
        return rows[:limit]

    ## Patch every module that reads or writes the table to use this one instead.
    def install(self, stack):
        for module in STORE_USERS:
            for name, function in (
                ("put_item", self.put_item),
                ("put_items", self.put_items),
                ("get_item", self.get_item),
                ("query_items", self.query_items),
            ):
                if hasattr(__import__(module, fromlist=["_"]), name):
                    stack.enter_context(patch(f"{module}.{name}", function))


## Return an OCC call symbol expiring inside the covered-call DTE window.
def call_symbol(strike):
    expiration = (date.today() + timedelta(days=35)).strftime("%y%m%d")
    return f"{TICKER}{expiration}C{int(strike * 1000):08d}"


## Build one call snapshot shaped like Alpaca's option-chain response.
def call_snapshot(bid, ask, delta):
    return SimpleNamespace(
        latest_quote=SimpleNamespace(bid_price=bid, ask_price=ask, bid_size=5, ask_size=5),
        greeks=SimpleNamespace(delta=delta),
        implied_volatility=0.30,
    )


class CoveredCallWheelEndToEndTests(unittest.TestCase):
    ## One covered call: scanned from real holdings, placed against live shares, then called away.
    def test_shares_from_an_assigned_put_are_scanned_placed_and_called_away(self):
        table = FakeTable()
        contract_symbol = call_symbol(STRIKE)
        shares_position = {
            "strategy": "stock",
            "ticker_symbol": TICKER,
            "quantity": 100,
            "average_entry_price": BROKER_COST_BASIS,
        }

        with ExitStack() as stack:
            table.install(stack)

            # The put that started the wheel: assigned, with its share result still open.
            table.put_item({
                "pk": f"USER#{USER_ID}",
                "sk": "OUTCOME#2026-07-02T00:00:00+00:00#put-1",
                "item_type": "completed_outcome",
                "status": "complete",
                "assigned": True,
                "option_type": "put",
                "underlying_outcome_pending": True,
                "ticker_symbol": TICKER,
                "quantity": 1,
                "opening_credit": ASSIGNMENT_PREMIUM,
                "effective_share_cost": REAL_COST_BASIS,
                "completed_at": "2026-07-02T00:00:00+00:00",
            })

            # 1. The premium collected on the assigned put lowers what the shares really cost.
            holdings = build_holdings(USER_ID, [shares_position])
            self.assertEqual(holdings[TICKER]["broker_cost_basis"], BROKER_COST_BASIS)
            self.assertEqual(holdings[TICKER]["cost_basis"], REAL_COST_BASIS)
            self.assertEqual(holdings[TICKER]["uncovered_shares"], 100)

            # 2. Scanning finds calls above that cost basis and rejects the ones below it.
            option_data_client = Mock()
            option_data_client.get_option_chain.return_value = {
                contract_symbol: call_snapshot(2.00, 2.10, 0.24),
                # Passes every shared threshold, but selling here would realize a loss.
                call_symbol(190.0): call_snapshot(2.40, 2.50, 0.27),
            }
            stock_data_client = Mock()
            stock_data_client.get_stock_latest_trade.return_value = {
                TICKER: SimpleNamespace(price=SHARE_PRICE, timestamp=datetime.now(timezone.utc))
            }

            # The model and the market/memory lookups are exercised by their own tests. Here they are
            # held still so the run is offline and deterministic, and the local review stands in for the model.
            stack.enter_context(patch("backend.strategy.recommender.build_candidate_review_context", return_value={}))
            stack.enter_context(patch("backend.strategy.recommender.build_memory_context", return_value={}))
            stack.enter_context(patch("backend.strategy.ai_review.get_openai_client", return_value=None))

            results = get_recommendation_results(
                COVERED_CALL,
                USER_ID,
                total_capital=100_000,
                portfolio_context={"holdings": holdings},
                stock_data_client=stock_data_client,
                option_data_client=option_data_client,
            )
            candidates = candidates_to_records(results["candidates"])
            self.assertEqual([candidate["strike"] for candidate in candidates], [STRIKE])
            self.assertEqual(candidates[0]["costBasis"], REAL_COST_BASIS)

            # 3. The saved run keeps the columns a covered call is priced from.
            run = save_recommendation_run(
                USER_ID,
                candidates,
                results["review"],
                strategy_rules=COVERED_CALL.strategy_rules,
            )
            saved_candidate = run["candidates"][0]
            self.assertEqual(saved_candidate["costBasis"], REAL_COST_BASIS)

            # 4. Placement re-checks the shares against the live account and reprices the quote.
            quote_client = Mock()
            quote_client.get_option_latest_quote.return_value = {
                contract_symbol: SimpleNamespace(model_dump=lambda mode="json": {
                    "bid_price": "2.20",
                    "ask_price": "2.30",
                    "bid_size": "4",
                    "ask_size": "4",
                    "timestamp": "2026-09-20T15:30:00Z",
                })
            }
            with patch("backend.api.services.get_paper_orders", return_value=[]), \
                 patch("backend.api.services.get_paper_account_summary", return_value={"available_csp_cash": 0.0}), \
                 patch("backend.api.services.get_paper_positions", return_value=[shares_position]):
                placement = prepare_candidate_for_paper_order(
                    USER_ID,
                    {**run, "created_at": datetime.now(timezone.utc).isoformat()},
                    saved_candidate,
                    "helios-e2e-order",
                    Mock(),
                    quote_client,
                )

            placed_candidate = placement["candidate"]
            self.assertEqual(placement["strategy"].key, COVERED_CALL.key)
            # Repriced from the live 2.20 bid, against the real cost basis.
            self.assertAlmostEqual(placed_candidate["premiumIfSoldAtBid"], 220.0)
            self.assertAlmostEqual(placed_candidate["maxProfitIfCalledAway"], (STRIKE - REAL_COST_BASIS) * 100 + 220.0)

            # 5. The order is recorded as a covered call: secured by shares, committing no cash.
            record_user_decision(
                USER_ID,
                run["id"],
                contract_symbol,
                "place_paper_order",
                alpaca_order={
                    "id": "alpaca-e2e",
                    "status": "filled",
                    "filled_qty": "1",
                    "filled_avg_price": "2.20",
                    "filled_at": "2026-09-20T15:31:00+00:00",
                },
                candidate_override=placed_candidate,
                strategy=COVERED_CALL,
            )
            order = next(
                item for item in table.items.values() if item.get("item_type") == "paper_order"
            )
            self.assertEqual(order["strategy"], "covered call")
            self.assertEqual(order["cash_required"], 0)
            self.assertEqual(order["cost_basis"], REAL_COST_BASIS)
            self.assertAlmostEqual(order["premium_received"], 220.0)

            # 6. The call is exercised: the shares are delivered and the wheel closes.
            with patch("backend.memory.outcomes.get_recent_outcome_snapshots", return_value=[]):
                finalization = finalize_trade_outcomes(
                    USER_ID,
                    live_positions=[],
                    broker_orders=[],
                    option_activities=[{
                        "id": "activity-e2e",
                        "activity_type": "OPASN",
                        "symbol": contract_symbol,
                        "date": "2026-10-25",
                    }],
                )

            self.assertEqual(finalization["completed"], 1)
            self.assertEqual(finalization["assignments_settled"], 1)

            call_outcome = finalization["outcomes"][0]
            self.assertEqual(call_outcome["option_type"], "call")
            self.assertEqual(call_outcome["shares_called_away"], 100)
            self.assertEqual(call_outcome["share_sale_proceeds"], STRIKE * 100)
            # Sold at 210 shares that really cost 197.
            self.assertEqual(call_outcome["share_realized_pnl"], (STRIKE - REAL_COST_BASIS) * 100)
            self.assertFalse(call_outcome["underlying_outcome_pending"])

            settled_put = table.get_item(f"USER#{USER_ID}", "OUTCOME#2026-07-02T00:00:00+00:00#put-1")
            self.assertFalse(settled_put["underlying_outcome_pending"])
            self.assertEqual(settled_put["underlying_resolution"], "called_away")
            self.assertEqual(settled_put["underlying_realized_pnl"], (STRIKE - REAL_COST_BASIS) * 100)

            # 7. With the shares gone, their premium no longer discounts anything still held.
            self.assertEqual(build_holdings(USER_ID, []), {})
            remaining = build_holdings(USER_ID, [{**shares_position, "quantity": 100}])
            self.assertEqual(remaining[TICKER]["cost_basis"], BROKER_COST_BASIS)


if __name__ == "__main__":
    unittest.main()
