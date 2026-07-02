## DynamoDB-backed episodic, outcome, and user-profile memory facade.

from backend.memory import dynamodb_store


## Delegate learning-memory construction to the active memory store.
## The strategy and market agents use this wrapper to avoid importing DynamoDB internals directly.
def build_memory_context(ticker_symbols):
    return dynamodb_store.build_memory_context(ticker_symbols)
