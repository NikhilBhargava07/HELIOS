## DynamoDB-backed recommendation memory facade.
##
## API and strategy modules import from this file so storage details stay behind
## the memory boundary. The implementation delegates to the active DynamoDB
## single-table store.

from backend.memory import dynamodb_store


## Find a contract inside a previously saved recommendation run.
def find_candidate(run, contract_symbol):
    return dynamodb_store.find_candidate(run, contract_symbol)


## Load one recommendation run and all saved candidates.
def get_recommendation_run(run_id):
    return dynamodb_store.get_recommendation_run(run_id)


## Load the most recently generated recommendation run.
def get_latest_recommendation_run():
    return dynamodb_store.get_latest_recommendation_run()


## Save an AI review and the complete evidence snapshot it received.
def save_recommendation_run(
    candidates,
    review,
    market_context=None,
    strategy_rules=None,
    portfolio_context=None,
    memory_context=None,
):
    return dynamodb_store.save_recommendation_run(
        candidates,
        review,
        market_context=market_context,
        strategy_rules=strategy_rules,
        portfolio_context=portfolio_context,
        memory_context=memory_context,
    )
