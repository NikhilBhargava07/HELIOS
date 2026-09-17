## The strategies HELIOS knows how to scan, looked up by their stored key.
##
## Routes and workers refer to strategies by key so a saved recommendation can
## always be traced back to the rules that produced it. Registering a strategy
## here is the only step needed to make it scannable.

from backend.strategy.cash_secured_put import CASH_SECURED_PUT

STRATEGIES = {
    CASH_SECURED_PUT.key: CASH_SECURED_PUT,
}

DEFAULT_STRATEGY_KEY = CASH_SECURED_PUT.key


## Return one registered strategy, or raise if the key is unknown.
## Failing loudly keeps an unrecognized key from silently scanning the wrong rules.
def get_strategy(key):
    strategy = STRATEGIES.get(key)
    if strategy is None:
        raise ValueError(f"Unknown strategy: {key}")

    return strategy
