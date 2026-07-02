## Normalize memory payloads before persisting them to DynamoDB.


## Convert candidate objects into simple dictionaries before storing them.
## This strips pandas-specific values so DynamoDB and JSON responses receive predictable primitive fields.
def normalize_candidate(candidate):
    return {
        "tickerSymbol": candidate["tickerSymbol"],
        "contractSymbol": candidate["contractSymbol"],
        "expiration": candidate["expiration"],
        "DTE": candidate["DTE"],
        "strike": candidate["strike"],
        "currentStockPrice": candidate.get("currentStockPrice"),
        "delta": candidate.get("delta"),
        "ivPercent": candidate.get("ivPercent"),
        "spread": candidate.get("spread"),
        "premiumIfSoldAtBid": candidate.get("premiumIfSoldAtBid"),
        "cashRequired": candidate.get("cashRequired"),
        "breakevenPrice": candidate.get("breakevenPrice"),
        "returnOnCashPercent": candidate.get("returnOnCashPercent"),
        "companyName": candidate.get("companyName"),
    }
