## Define what a tradable strategy is, so adding one is a declaration rather than a new code path.
##
## Every strategy runs the same course: decide which tickers it may consider,
## build a table of candidates, let the model review that table under rules it
## cannot relax, and save the result. A strategy supplies only the parts that
## genuinely differ, and how it gathers candidates is one of them: an option
## strategy pulls a chain per ticker, while a stock strategy reads one batch of
## price history for the whole universe.

from dataclasses import dataclass
from typing import Callable, Optional

from backend.config import MAX_RECOMMENDATIONS


## The deterministic thresholds a candidate must satisfy before the model ever sees it.
## These are exactly the rules the AI is never permitted to relax.
@dataclass(frozen=True)
class OptionRules:
    min_dte: int
    max_dte: int
    target_delta: float
    delta_tolerance: float
    max_spread: float
    min_quote_size: int
    min_iv_percent: float
    max_iv_percent: float
    min_roc_percent: float


## The parts of a model review that genuinely differ between strategies.
##
## Only these three vary. The system message, response schema, and cache key are
## shared on purpose: they precede the prompt, so any strategy-specific wording
## there would stop strategies from sharing a cached prefix.
@dataclass(frozen=True)
class ReviewConfig:
    guidance: str
    summarize_candidate: Callable
    local_review: Callable


## Everything the placement gate knows about the account at the moment an order would be sent.
##
## Placement is judged against live broker state, never against the scan that
## produced the candidate. Unfilled sell orders are included because they already
## commit the collateral behind them even though they are not yet positions.
@dataclass(frozen=True)
class PlacementContext:
    user_id: str
    account: dict
    total_capital: float
    positions: tuple
    active_sell_orders: tuple


## Everything a scan needs to build candidates, whatever shape those candidates take.
##
## The account state travels with the scan because some strategies price against
## it: a covered call needs the real cost basis of shares already held, and a
## stock recommendation needs to know what is already owned before suggesting more.
@dataclass(frozen=True)
class ScanContext:
    available_capital: Optional[float]
    latest_prices: dict
    portfolio_context: dict
    stock_data_client: object
    option_data_client: object


## One scan's candidates, plus the tickers it could not read.
## Failures are carried rather than raised so one unreadable ticker cannot end a scan of thirty.
@dataclass(frozen=True)
class ScanResult:
    candidates: object
    errors: tuple = ()


## What every strategy declares, whatever it trades.
##
## capital_column names the column holding the cash a position locks up, or None
## for strategies secured by something other than cash. A covered call is secured
## by shares already owned, so it commits no buying power and sets this to None.
## collateral_basis_column names the column holding what that other collateral
## cost, which a covered call measures its breakeven from in place of the strike.
##
## find_candidates builds the table the model reviews and owns how it is gathered.
## eligibility_requirement explains in plain words why no ticker qualified, since
## "no candidates found" would hide the real reason.
##
## rank_column orders candidates before the model sees them, and max_candidates
## caps how many it sees. A strategy with no meaningful ranking leaves rank_column
## empty rather than inventing one, because a fabricated ordering would quietly
## become a recommendation of its own.
##
## secure_candidate is the last gate before a real order. It confirms against live
## broker state that the collateral this strategy requires is actually there and
## still free, raising ValueError with a plain explanation when it is not, and
## returns the economics tied to that collateral so the final quote is repriced
## against what truly secures the contract rather than against the scan. A strategy
## HELIOS only advises on refuses here, because there is no order for it to place.
@dataclass(frozen=True, kw_only=True)
class Strategy:
    key: str
    short_label: str
    stored_name: str
    capital_column: Optional[str]
    collateral_basis_column: Optional[str]
    candidate_id_column: str
    display_columns: tuple
    eligible_tickers: Callable
    find_candidates: Callable
    strategy_rules: dict
    review: ReviewConfig
    eligibility_requirement: str
    secure_candidate: Callable
    rank_column: Optional[str] = None
    max_candidates: Optional[int] = MAX_RECOMMENDATIONS


## One option strategy: everything above, plus what it takes to price a contract.
##
## bind_economics returns economics tied to one ticker's holding, such as the real
## cost basis of shares a covered call would sell. extra_filters are hard rules
## beyond the shared thresholds, applied in the same pipeline so the model never
## sees a contract that broke one.
@dataclass(frozen=True, kw_only=True)
class OptionStrategy(Strategy):
    contract_type: object
    rules: OptionRules
    economics: Callable
    bind_economics: Optional[Callable] = None
    extra_filters: tuple = ()
