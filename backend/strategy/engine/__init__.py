## Strategy-neutral machinery shared by every option strategy.
##
## Nothing in this package knows what a cash-secured put or a covered call is.
## It fetches chains, enforces thresholds, and ranks rows; each strategy supplies
## the economics that give those rows meaning.
