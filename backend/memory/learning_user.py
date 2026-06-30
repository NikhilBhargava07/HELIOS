## DynamoDB-backed episodic, outcome, and user-profile memory facade.

from backend.memory import dynamodb_store


## Build compact historical context for a recommendation request.
def build_memory_context(ticker_symbols):
    return dynamodb_store.build_memory_context(ticker_symbols)
