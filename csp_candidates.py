import pandas as pd
from dte import *

def find_csp_candidates(ticker, min_dte, max_dte, min_volume, min_open_interest):
    all_candidates = []
    for expiration in ticker.options:
        dte = calculate_dte(expiration)
        if dte < min_dte or dte > max_dte:
            continue
        chain = ticker.option_chain(expiration)
        puts = chain.puts.copy()
        puts["expiration"] = expiration
        puts["DTE"] = dte
        puts["ivPercent"] = puts["impliedVolatility"] * 100
        puts["spread"] = puts["ask"] - puts["bid"]
        puts["cashRequired"] = puts["strike"] * 100
        puts["premiumIfSoldAtBid"] = puts["bid"] * 100
        filtered_puts = puts[
            (puts["bid"] > 0)
            & (puts["ask"] > 0)
            & (puts["volume"] >= min_volume)
            & (puts["openInterest"] >= min_open_interest)
            & (puts["spread"] > 0)
            & (puts["spread"] <= 0.50)
        ]
        all_candidates.append(filtered_puts)

    if not all_candidates:
        return pd.DataFrame()

    result = pd.concat(all_candidates)
    columns = [
        "contractSymbol",
        "expiration",
        "DTE",
        "strike",
        "bid",
        "ask",
        "spread",
        "volume",
        "openInterest",
        "ivPercent",
        "cashRequired",
        "premiumIfSoldAtBid",
    ]

    return result[columns].sort_values(by=["DTE", "strike"])