## DynamoDB-backed recommendation memory facade.
##
## API and strategy modules import from this file so storage details stay behind
## the memory boundary. The implementation delegates to the active DynamoDB
## single-table store.

from backend.memory import dynamodb_store


## Delegate candidate lookup to the active memory store.
## This wrapper keeps route code independent from whether memory is DynamoDB or another backend later.
def find_candidate(run, contract_symbol):
    return dynamodb_store.find_candidate(run, contract_symbol)


## Delegate recommendation-run retrieval to the active memory store.
## Keeping this boundary thin makes future storage migrations easier.
def get_recommendation_run(run_id):
    return dynamodb_store.get_recommendation_run(run_id)


## Delegate latest-run lookup to the active memory store.
## The AI market take uses this to compare current conditions with the most recent recommendation set.
def get_latest_recommendation_run():
    return dynamodb_store.get_latest_recommendation_run()


## Delegate recommendation-run persistence to the active memory store.
## Saving through this wrapper avoids spreading DynamoDB details across strategy code.
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
