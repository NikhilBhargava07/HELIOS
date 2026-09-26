/**
 * Declare how each strategy presents itself, so one set of renderers can show all of them.
 *
 * The backend decides what a candidate is and which numbers matter; this file decides
 * how those numbers read on screen. Adding a strategy here is a declaration, the same
 * way it is on the backend, rather than another branch inside the renderers.
 *
 * canPlace is the one field that changes behavior rather than wording: a strategy HELIOS
 * only advises on offers no place button at all, so the UI cannot imply an action the
 * backend would refuse.
 */

/** Describe a contract the way both option strategies do: company, expiry, and days left. */
const optionSubline = candidate =>
    `${escapeHtml(companyNameForTicker(candidate.tickerSymbol))} · ${escapeHtml(candidate.expiration)} · ${candidate.DTE} DTE`;

/** Label a contract compactly by the days it has left to run. */
const optionShortMeta = candidate => `${candidate.DTE}d`;

const STRATEGY_VIEWS = {
    cash_secured_put: {
        label: "Cash-secured puts",
        scanLabel: "CSP scan",
        subhead: "Scans approved tickers, applies hard safety filters, then asks the agent to review the top candidates.",
        // Selling a put ties up cash, so a candidate the account can no longer back is hidden.
        limitedByCash: true,
        canPlace: true,
        idOf: candidate => candidate.contractSymbol,
        underlyingLabel: "Underlying",
        headline: candidate => `Sell 1 ${tickerTooltip(candidate.tickerSymbol)} $${Number(candidate.strike)} put`,
        subline: optionSubline,
        shortName: candidate => `${tickerTooltip(candidate.tickerSymbol)} $${Number(candidate.strike)}P`,
        shortMeta: optionShortMeta,
        heroStats: candidate => [
            { label: "Premium", value: money(candidate.premiumIfSoldAtBid), tone: "rec-pos" },
            { label: "Return on cash", value: percent(candidate.returnOnCashPercent) },
            { label: "Delta", value: Number(candidate.delta).toFixed(2) },
        ],
        compactStats: candidate => [
            { label: "Prem", value: money(candidate.premiumIfSoldAtBid), tone: "rec-pos" },
            { label: "ROC", value: percent(candidate.returnOnCashPercent) },
            { label: "&Delta;", value: Number(candidate.delta).toFixed(2) },
        ],
        details: candidate => [
            { label: "IV", value: percent(candidate.ivPercent) },
            { label: "Spread", value: money(candidate.spread) },
            { label: "Cash required", value: money(candidate.cashRequired) },
            { label: "Breakeven", value: money(candidate.breakevenPrice) },
        ],
        // Plain text for toasts, which escape their content rather than render markup.
        orderLabel: candidate => `${candidate.tickerSymbol} ${money(candidate.strike)} put`,
    },

    covered_call: {
        label: "Covered calls",
        scanLabel: "covered call scan",
        subhead: "Scans stocks you already own, keeps every strike at or above what those shares really cost, then asks the agent to review them.",
        // Shares secure a covered call, so buying power never limits which ones are shown.
        limitedByCash: false,
        canPlace: true,
        idOf: candidate => candidate.contractSymbol,
        underlyingLabel: "Underlying",
        headline: candidate => `Sell 1 ${tickerTooltip(candidate.tickerSymbol)} $${Number(candidate.strike)} call`,
        subline: optionSubline,
        shortName: candidate => `${tickerTooltip(candidate.tickerSymbol)} $${Number(candidate.strike)}C`,
        shortMeta: optionShortMeta,
        heroStats: candidate => [
            { label: "Premium", value: money(candidate.premiumIfSoldAtBid), tone: "rec-pos" },
            { label: "If called away", value: money(candidate.maxProfitIfCalledAway), tone: "rec-pos" },
            { label: "Delta", value: Number(candidate.delta).toFixed(2) },
        ],
        compactStats: candidate => [
            { label: "Prem", value: money(candidate.premiumIfSoldAtBid), tone: "rec-pos" },
            { label: "Called", value: money(candidate.maxProfitIfCalledAway) },
            { label: "&Delta;", value: Number(candidate.delta).toFixed(2) },
        ],
        details: candidate => [
            { label: "IV", value: percent(candidate.ivPercent) },
            { label: "Spread", value: money(candidate.spread) },
            { label: "Shares cost", value: money(candidate.costBasis) },
            { label: "Breakeven", value: money(candidate.breakevenPrice) },
        ],
        orderLabel: candidate => `${candidate.tickerSymbol} ${money(candidate.strike)} call`,
    },

    equity: {
        label: "Stocks",
        scanLabel: "stock scan",
        subhead: "Reviews approved stocks against recent price history and what you already own. HELIOS does not place stock orders.",
        limitedByCash: false,
        canPlace: false,
        advisoryNote: "HELIOS does not trade stocks. This is a recommendation to act on yourself.",
        idOf: candidate => candidate.tickerSymbol,
        underlyingLabel: null,
        headline: candidate => `${tickerTooltip(candidate.tickerSymbol)} at ${money(candidate.currentStockPrice)}`,
        subline: candidate => {
            const company = escapeHtml(companyNameForTicker(candidate.tickerSymbol));
            return candidate.sharesHeld
                ? `${company} · holding ${Number(candidate.sharesHeld)} shares`
                : `${company} · not currently held`;
        },
        shortName: candidate => tickerTooltip(candidate.tickerSymbol),
        shortMeta: candidate => money(candidate.currentStockPrice),
        heroStats: candidate => [
            { label: "1 month", value: signedPercent(candidate.percentChange1Month), tone: trendTone(candidate.percentChange1Month) },
            { label: "Year to date", value: signedPercent(candidate.percentChangeYTD), tone: trendTone(candidate.percentChangeYTD) },
            {
                label: candidate.sharesHeld ? "Your return" : "Your position",
                value: candidate.sharesHeld ? signedPercent(candidate.unrealizedReturnPercent) : "None",
                tone: candidate.sharesHeld ? trendTone(candidate.unrealizedReturnPercent) : "",
            },
        ],
        compactStats: candidate => [
            { label: "1M", value: signedPercent(candidate.percentChange1Month), tone: trendTone(candidate.percentChange1Month) },
            { label: "YTD", value: signedPercent(candidate.percentChangeYTD), tone: trendTone(candidate.percentChangeYTD) },
        ],
        details: candidate => [
            { label: "1 day", value: signedPercent(candidate.percentChange1Day) },
            { label: "5 day", value: signedPercent(candidate.percentChange5Day) },
            { label: "Shares held", value: candidate.sharesHeld ? Number(candidate.sharesHeld) : "—" },
            { label: "Your cost", value: candidate.costBasis ? money(candidate.costBasis) : "—" },
        ],
    },
};

const DEFAULT_STRATEGY_KEY = "cash_secured_put";

/**
 * Return the view for one strategy key, falling back to the default.
 * A saved run from a strategy this build does not know still renders rather than blanking the page.
 */
function strategyView(strategyKey) {
    return STRATEGY_VIEWS[strategyKey] || STRATEGY_VIEWS[DEFAULT_STRATEGY_KEY];
}

/**
 * Format a percentage with an explicit sign, since a stock's direction is the point.
 * Missing history reads as an em dash rather than zero, which would look like an unchanged price.
 */
function signedPercent(value) {
    if (value === null || value === undefined || Number.isNaN(Number(value))) {
        return "—";
    }

    const number = Number(value);
    return `${number > 0 ? "+" : ""}${number.toFixed(2)}%`;
}

/** Colour a movement green or red, leaving small moves and missing data neutral. */
function trendTone(value) {
    if (value === null || value === undefined || Number.isNaN(Number(value))) {
        return "";
    }

    const number = Number(value);
    if (number > NEUTRAL_TREND_PERCENT_THRESHOLD) {
        return "rec-pos";
    }

    return number < -NEUTRAL_TREND_PERCENT_THRESHOLD ? "rec-neg" : "";
}


/**
 * Return the identifier the active strategy uses for one candidate.
 * A contract is identified by its symbol and a stock by its ticker, so comparisons go through here.
 */
function candidateId(candidate) {
    return candidate ? strategyView(currentStrategyKey).idOf(candidate) : null;
}


/**
 * Hide candidates the account can no longer back, for strategies whose collateral is cash.
 * A covered call is secured by shares and a stock idea places no order, so neither is limited by buying power.
 */
function candidatesWithinLimits(candidates, availableCash) {
    return strategyView(currentStrategyKey).limitedByCash
        ? filterAffordableCandidates(candidates, availableCash)
        : (candidates || []);
}
