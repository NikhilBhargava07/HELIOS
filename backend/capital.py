## Decide how much of the account HELIOS may still commit.
##
## There is one rule: a share of the balance stays in cash. Everything else is available,
## and how it is divided between positions is the user's decision rather than a number
## HELIOS imposes. An earlier version gave each strategy a fixed slice of the account,
## which answered a question nobody had asked it to answer.
##
## This lives outside the strategy package deliberately: the dashboard and the
## order-placement path both need the same answer, and neither should have to
## import strategy code to get it.


## Return the reserve, what is investable beside it, and what of that is still unused.
## Committed capital never pushes availability below zero, so an over-committed account
## reports no capacity rather than a negative one.
def investable_capacity(total_capital, reserve_percent, committed_capital):
    total_capital = max(0, total_capital or 0)
    reserve = total_capital * reserve_percent
    investable = max(0, total_capital - reserve)

    return reserve, investable, max(0, investable - committed_capital)
