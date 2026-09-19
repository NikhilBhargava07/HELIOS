## Define what a tradable strategy is, so adding one is a declaration rather than a new code path.
##
## Every option strategy shares the same machinery: fetch a chain, drop anything
## that breaks a hard rule, rank what survives, and ask the model to review it.
## A strategy therefore supplies only the parts that genuinely differ, which are
## which contracts to fetch, what a contract is worth, what collateral it needs,
## which tickers it may even consider, and how to describe itself to the model.

from dataclasses import dataclass
from typing import Callable, Optional


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


## One option strategy: its identity, its hard rules, and the behavior unique to it.
##
## capital_column names the column holding the cash a contract locks up, or None
## for strategies secured by something other than cash. A covered call is secured
## by shares already owned, so it commits no buying power and sets this to None.
## collateral_basis_column names the column holding what that other collateral
## cost, which a covered call measures its breakeven from in place of the strike.
##
## The optional fields exist for strategies whose rules depend on the account.
## bind_economics returns economics tied to one ticker's holding, such as the real
## cost basis of shares a covered call would sell. extra_filters are hard rules
## beyond the shared thresholds, applied in the same pipeline so the model never
## sees a contract that broke one. eligibility_requirement explains in plain words
## why no ticker qualified, since "no candidates found" would hide the real reason.
##
## secure_candidate is the last gate before a real order. It confirms against live
## broker state that the collateral this strategy requires is actually there and
## still free, raising ValueError with a plain explanation when it is not, and
## returns the economics tied to that collateral so the final quote is repriced
## against what truly secures the contract rather than against the scan.
@dataclass(frozen=True)
class OptionStrategy:
    key: str
    short_label: str
    stored_name: str
    contract_type: object
    rules: OptionRules
    capital_column: Optional[str]
    collateral_basis_column: Optional[str]
    display_columns: tuple
    economics: Callable
    eligible_tickers: Callable
    strategy_rules: dict
    review: ReviewConfig
    eligibility_requirement: str
    secure_candidate: Callable
    bind_economics: Optional[Callable] = None
    extra_filters: tuple = ()
