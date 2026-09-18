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


## One option strategy: its identity, its hard rules, and the behavior unique to it.
##
## capital_column names the column holding the cash a contract locks up, or None
## for strategies secured by something other than cash. A covered call is secured
## by shares already owned, so it commits no buying power and sets this to None.
@dataclass(frozen=True)
class OptionStrategy:
    key: str
    short_label: str
    stored_name: str
    contract_type: object
    rules: OptionRules
    capital_column: Optional[str]
    display_columns: tuple
    economics: Callable
    eligible_tickers: Callable
    strategy_rules: dict
    review: ReviewConfig
