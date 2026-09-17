## Decide how much capital a strategy is still allowed to commit.
##
## Each strategy currently gets a fixed share of the account, so a single slow
## or crowded strategy cannot consume the whole balance. Moving to one shared
## limit across all strategies later means changing this function and nothing
## else, because every caller asks the question here rather than recomputing it.
##
## This lives outside the strategy package deliberately: the dashboard and the
## order-placement path both need the same answer, and neither should have to
## import strategy code to get it.


## Return one strategy's capital budget and how much of it remains unused.
## Committed capital never pushes availability below zero, so an over-committed account reports no capacity rather than a negative one.
def strategy_capacity(total_capital, budget_percent, committed_capital):
    budget = total_capital * budget_percent

    return budget, max(0, budget - committed_capital)
