## Fetch Alpaca option-chain data and turn it into plain candidate rows.
##
## This module knows about market data only. What a contract is actually worth
## depends on the strategy selling it, so the caller supplies an economics
## function and the same fetch serves puts sold against cash and calls sold
## against shares already owned.

from datetime import datetime, timedelta

import pandas as pd
from alpaca.data.enums import DataFeed, OptionsFeed
from alpaca.data.requests import OptionChainRequest, StockLatestTradeRequest

from backend.strategy.dates import calculate_dte


## Parse an OCC option contract symbol into expiration and strike.
## Candidate rows use this to display readable contract details and compute DTE.
def parse_option_symbol(contract_symbol):
    option_code = contract_symbol[-15:]
    expiration = datetime.strptime(option_code[:6], "%y%m%d").date()
    strike = int(option_code[7:]) / 1000

    return expiration, strike


## Fetch the latest stock price for one ticker from Alpaca.
## The current underlying price is needed for strike distance, breakeven context, and dashboard display.
def get_latest_stock_price(ticker_symbol, stock_data_client):
    request = StockLatestTradeRequest(
        symbol_or_symbols=ticker_symbol,
        feed=DataFeed.IEX,
    )

    latest_trades = stock_data_client.get_stock_latest_trade(request)

    return latest_trades[ticker_symbol].price


## Request the contracts of one type expiring inside the strategy's window.
## Narrowing by expiration at the broker keeps the scan from pulling chains it would immediately discard.
def fetch_option_snapshots(
    ticker_symbol,
    contract_type,
    min_dte,
    max_dte,
    option_data_client,
):
    today = datetime.today().date()
    request = OptionChainRequest(
        underlying_symbol=ticker_symbol,
        type=contract_type,
        feed=OptionsFeed.INDICATIVE,
        expiration_date_gte=(today + timedelta(days=min_dte)).strftime("%Y-%m-%d"),
        expiration_date_lte=(today + timedelta(days=max_dte)).strftime("%Y-%m-%d"),
    )

    return option_data_client.get_option_chain(request)


## Summarize the market facts of one option candidate for the model.
## Every option strategy sends these same quote fields, so each strategy adds only the economics that make it distinct.
def summarize_option_market(candidate):
    return {
        "ticker_symbol": candidate.tickerSymbol,
        "contract_symbol": candidate.contractSymbol,
        "expiration": candidate.expiration,
        "dte": int(candidate.DTE),
        "strike": float(candidate.strike),
        "current_stock_price": float(candidate.currentStockPrice),
        "delta": float(candidate.delta),
        "iv_percent": float(candidate.ivPercent),
        "bid": float(candidate.bid),
        "ask": float(candidate.ask),
        "spread": float(candidate.spread),
        "bid_size": int(getattr(candidate, "bidSize", 0) or 0),
        "ask_size": int(getattr(candidate, "askSize", 0) or 0),
        "premium": float(candidate.premiumIfSoldAtBid),
    }


## Convert option snapshots into one table of quotes, greeks, and strategy economics.
## Contracts without a usable quote are dropped here rather than being carried through the filters as empty rows.
def build_candidate_rows(ticker_symbol, snapshots, current_stock_price, economics):
    rows = []

    for contract_symbol, snapshot in snapshots.items():
        quote = snapshot.latest_quote

        if quote is None:
            continue

        greeks = snapshot.greeks
        expiration, strike = parse_option_symbol(contract_symbol)
        expiration_text = expiration.strftime("%Y-%m-%d")
        bid = quote.bid_price
        ask = quote.ask_price
        dte = calculate_dte(expiration_text)

        row = {
            "tickerSymbol": ticker_symbol,
            "contractSymbol": contract_symbol,
            "expiration": expiration_text,
            "DTE": dte,
            "strike": strike,
            "currentStockPrice": current_stock_price,
            "bid": bid,
            "ask": ask,
            "spread": ask - bid,
            "bidSize": quote.bid_size,
            "askSize": quote.ask_size,
            "impliedVolatility": snapshot.implied_volatility,
            "ivPercent": snapshot.implied_volatility * 100 if snapshot.implied_volatility else None,
            "delta": greeks.delta if greeks else None,
        }
        row.update(
            economics(
                strike=strike,
                bid=bid,
                current_stock_price=current_stock_price,
                dte=dte,
            )
        )
        rows.append(row)

    return pd.DataFrame(rows)
