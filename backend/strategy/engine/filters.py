## Enforce the hard thresholds that decide which contracts the model may review.
##
## Every filter here is strategy-neutral: it compares a column against a rule.
## Which target delta or collateral limit applies comes from the strategy, so
## the same pipeline governs a put sold for cash and a call sold against shares.


## Remove contracts without usable bid, ask, or quoted size.
## This prevents stale or incomplete option quotes from entering the later safety filters.
def filter_valid_quotes(contracts, max_spread, min_quote_size):
    return contracts[
        (contracts["bid"] > 0)
        & (contracts["ask"] > 0)
        & (contracts["spread"] > 0)
        & (contracts["spread"] <= max_spread)
        & (contracts["bidSize"] >= min_quote_size)
        & (contracts["askSize"] >= min_quote_size)
    ]


## Keep contracts near the strategy's target delta.
## Delta is used as a proxy for assignment probability and option sensitivity.
def filter_by_delta(contracts, target_delta, delta_tolerance):
    min_delta = target_delta - delta_tolerance
    max_delta = target_delta + delta_tolerance

    return contracts[
        (contracts["delta"] >= min_delta)
        & (contracts["delta"] <= max_delta)
    ]


## Keep implied volatility inside the strategy's acceptable range.
## The filter seeks enough premium to matter while avoiding extreme volatility that may signal outsized risk.
def filter_by_iv(contracts, min_iv_percent, max_iv_percent):
    return contracts[
        (contracts["ivPercent"] >= min_iv_percent)
        & (contracts["ivPercent"] <= max_iv_percent)
    ]


## Keep contracts above the minimum return threshold.
## This ensures a candidate offers enough premium relative to the collateral it ties up.
def filter_by_roc(contracts, min_roc_percent):
    return contracts[contracts["returnOnCashPercent"] >= min_roc_percent]


## Keep only contracts the account can currently collateralize.
## Strategies secured by something other than cash pass no capital column and skip this rule entirely.
def filter_by_capital(contracts, capital_column, available_capital):
    if not capital_column:
        return contracts

    return contracts[contracts[capital_column] <= available_capital]


## Apply the full hard-filter pipeline in order.
## Strategy-specific rules run last in the same pipeline, so the model only ever reviews contracts that satisfied every rule.
def apply_option_filters(
    contracts,
    rules,
    capital_column,
    available_capital,
    extra_filters=(),
):
    filtered = filter_valid_quotes(contracts, rules.max_spread, rules.min_quote_size)
    filtered = filter_by_delta(filtered, rules.target_delta, rules.delta_tolerance)
    filtered = filter_by_iv(filtered, rules.min_iv_percent, rules.max_iv_percent)
    filtered = filter_by_roc(filtered, rules.min_roc_percent)
    filtered = filter_by_capital(filtered, capital_column, available_capital)

    for extra_filter in extra_filters:
        filtered = extra_filter(filtered)

    return filtered
