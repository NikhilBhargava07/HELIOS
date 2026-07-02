/** Format values and build small, reusable HTML fragments safely. */

/**
 * Format a numeric value as US currency for user-facing stats.
 * Centralizing currency formatting keeps candidate cards, dashboard rows, and order messages consistent.
 */
function money(value) {
    return `$${Number(value).toLocaleString(undefined, {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
    })}`;
}

/**
 * Find a loaded candidate by its OCC contract symbol.
 * User actions reference contract symbols, so this helper ties button clicks back to the exact candidate object that was rendered.
 */
function candidateByContract(contractSymbol) {
    return candidatePool.find(candidate => candidate.contractSymbol === contractSymbol);
}

/**
 * Check whether the account can fully cash-secure a candidate.
 * A CSP should not be shown as placeable if its cash requirement exceeds current effective CSP cash.
 */
function candidateIsAffordable(candidate, availableCash) {
    if (availableCash === null || availableCash === undefined) {
        return true;
    }

    return Number(candidate.cashRequired || 0) <= Number(availableCash);
}

/**
 * Remove candidates that exceed current effective CSP cash.
 * This frontend guard mirrors backend safety logic so the UI does not encourage orders Alpaca will reject.
 */
function filterAffordableCandidates(candidates, availableCash) {
    return (candidates || []).filter(candidate => candidateIsAffordable(candidate, availableCash));
}

/**
 * Check whether the AI-selected contract is still in the affordable display set.
 * Buying power can change between recommendation generation and rendering, so the selected contract may need a safety override.
 */
function selectedContractIsAffordable(review, candidates) {
    if (!review?.selected_contract) {
        return false;
    }

    return candidates.some(candidate => candidate.contractSymbol === review.selected_contract);
}

/**
 * Adjust the displayed AI review if its selected contract is no longer affordable.
 * This preserves the model explanation while preventing the main action button from pointing at a trade the account cannot back.
 */
function reviewWithAffordableSelection(review, candidates, availableCash) {
    if (!review || selectedContractIsAffordable(review, candidates)) {
        return review;
    }

    if (!candidates.length) {
        const cashText = availableCash === null || availableCash === undefined
            ? "current buying power"
            : money(availableCash);

        return {
            decision: "reject_all",
            selected_contract: null,
            summary: `No displayed CSP can be backed by ${cashText} of available CSP cash.`,
            risk_note: "The app is filtering out contracts that would fail the cash-secured requirement before you try to place them.",
        };
    }

    return {
        ...review,
        selected_contract: candidates[0].contractSymbol,
        summary: `${review.summary} The original agent selection is not currently affordable, so the app is showing the best affordable displayed candidate instead.`,
        risk_note: `${review.risk_note} Cash availability can change after orders, open positions, or Alpaca buying-power updates.`,
    };
}

/**
 * Display a temporary success or failure notification.
 * Toasts give immediate feedback after paper-place or discard actions so the user does not have to visit another tab to confirm something happened.
 */
function showToast(title, message, variant = "success") {
    toastEl.classList.toggle("error", variant === "error");
    toastEl.innerHTML = `
        <strong>${escapeHtml(title)}</strong>
        <span>${escapeHtml(message)}</span>
    `;
    toastEl.classList.remove("hidden");

    clearTimeout(showToast.timeoutId);
    showToast.timeoutId = setTimeout(() => {
        toastEl.classList.add("hidden");
    }, TOAST_TIMEOUT_MS);
}

/**
 * Format a percentage without forcing a direction sign.
 * Metrics like IV and ROC are naturally positive values, so they use this cleaner formatter.
 */
function percent(value) {
    if (value === null || value === undefined) {
        return "n/a";
    }

    return `${Number(value).toFixed(2)}%`;
}

/**
 * Format a percentage with positive or negative direction.
 * Trend movement needs the sign because up/down direction changes the meaning of the value.
 */
function signedPercent(value) {
    if (value === null || value === undefined) {
        return "n/a";
    }

    const number = Number(value);
    const sign = number > 0 ? "+" : "";

    return `${sign}${number.toFixed(2)}%`;
}

/**
 * Format a dollar change with positive or negative direction.
 * Market trends and P&L rows use this to distinguish gains from losses without extra labels.
 */
function signedMoney(value) {
    if (value === null || value === undefined) {
        return "n/a";
    }

    const number = Number(value);
    const sign = number > 0 ? "+" : number < 0 ? "-" : "";

    return `${sign}${money(Math.abs(number))}`;
}

/**
 * Choose the CSS class for positive, negative, or neutral movement.
 * Small moves inside the neutral threshold stay white, while meaningful up/down moves become green or red.
 */
function trendDirectionClass(percentValue) {
    if (percentValue === null || percentValue === undefined) {
        return "trend-neutral";
    }

    const number = Number(percentValue);

    if (Math.abs(number) <= NEUTRAL_TREND_PERCENT_THRESHOLD) {
        return "trend-neutral";
    }

    return number > 0 ? "trend-up" : "trend-down";
}

/**
 * Build one rotating percentage/dollar trend row.
 * The row contains both values so CSS can rotate views without re-rendering the whole trend card.
 */
function trendMetric(label, percentValue, dollarValue) {
    const directionClass = trendDirectionClass(percentValue);

    return `
        <div class="trend-metric">
            <span class="label">${label}:</span>
            <span class="trend-value-window" aria-label="${label} move">
                <span class="trend-value percent-value ${directionClass}">${signedPercent(percentValue)}</span>
                <span class="trend-value dollar-value ${directionClass}">${signedMoney(dollarValue)}</span>
            </span>
        </div>
    `;
}

/**
 * Format a current price while handling unavailable quotes.
 * Market-data APIs can occasionally miss a quote, so the UI needs a readable fallback.
 */
function priceText(value) {
    if (value === null || value === undefined) {
        return "Price n/a";
    }

    return money(value);
}

/**
 * Format an RSS timestamp into a compact news-card date.
 * Invalid or missing feed dates are handled explicitly so the News page never shows confusing raw timestamps.
 */
function newsDateText(value) {
    if (!value) {
        return "Date unavailable";
    }

    const date = new Date(value);
    if (Number.isNaN(date.getTime())) {
        return "Date unavailable";
    }

    return date.toLocaleDateString(undefined, {
        month: "short",
        day: "numeric",
        year: "numeric",
    });
}

/**
 * Resolve a ticker to its display company name.
 * Tooltip rendering depends on this mapping so users can learn symbols without cluttering every card.
 */
function companyNameForTicker(ticker) {
    return companyNames[ticker] || ticker;
}

/**
 * Render a ticker with a keyboard-accessible company-name tooltip.
 * This keeps ticker displays sleek while still explaining names like WMT, CSCO, or QQQ on hover/focus.
 */
function tickerTooltip(ticker) {
    const companyName = companyNameForTicker(ticker);

    if (!ticker || companyName === ticker) {
        return escapeHtml(ticker || "");
    }

    return `
        <span class="ticker-tooltip" tabindex="0">
            ${escapeHtml(ticker)}
            <span class="tooltip-bubble">${escapeHtml(companyName)}</span>
        </span>
    `;
}

/**
 * Convert backend decision identifiers into title-cased text.
 * Values like reject_all are useful for code but should read naturally in the Agent Review panel.
 */
function formatDecision(value) {
    return String(value || "")
        .replaceAll("_", " ")
        .replace(/\b\w/g, letter => letter.toUpperCase());
}

/**
 * Describe whether an order filled, was canceled, or is still pending.
 * The Capital page uses this to distinguish active paper orders from completed broker events.
 */
function orderStatusText(order) {
    const status = String(order.status || "unknown").toLowerCase();
    if (status === "filled") {
        return "Filled";
    }
    if (["canceled", "expired", "rejected"].includes(status)) {
        return formatDecision(status);
    }
    return `${formatDecision(status)} · Awaiting fill`;
}

/**
 * Return the actual fill credit or requested limit credit per share.
 * Alpaca orders may be accepted but not filled, so this helper explains which price the user is seeing.
 */
function orderCreditText(order) {
    const filledPrice = Number(order.filled_avg_price);
    if (Number.isFinite(filledPrice) && filledPrice > 0) {
        return `Filled credit ${money(filledPrice)} per share`;
    }
    const limitPrice = Number(order.alpaca_limit_price);
    if (Number.isFinite(limitPrice) && limitPrice > 0) {
        return `Limit credit ${money(limitPrice)} per share`;
    }
    return `Quoted contract credit ${money(order.premium_received)}`;
}

/**
 * Escape untrusted text before inserting it into HTML templates.
 * News headlines, model output, and broker strings can contain special characters, so escaping protects the page from accidental markup injection.
 */
function escapeHtml(value) {
    return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
}

/**
 * Allow only HTTP(S) links from external news content.
 * RSS feeds are external input, so unsafe or malformed URLs are replaced with a harmless placeholder.
 */
function safeExternalUrl(value) {
    try {
        const url = new URL(String(value || ""));
        return ["http:", "https:"].includes(url.protocol) ? url.href : "#";
    } catch {
        return "#";
    }
}

/**
 * Render one glossary term and its explanatory tooltip.
 * The AI Market Take can use options vocabulary without forcing long definitions into the main paragraph.
 */
function glossaryTerm(term) {
    return `
        <span class="tooltip-term" tabindex="0">
            ${escapeHtml(term)}
            <span class="tooltip-bubble">${escapeHtml(GLOSSARY[term])}</span>
        </span>
    `;
}

/**
 * Render a list of glossary terms as compact hover chips.
 * This gives beginners optional context while preserving the clean Market Take layout.
 */
function renderGlossaryChips(terms) {
    return terms.map(term => `
        <span class="glossary-chip">
            ${glossaryTerm(term)}
        </span>
    `).join("");
}

/** Select glossary terms that appear in or help explain an AI take. */
/**
 * Choose glossary terms that are relevant to the current AI market take.
 * The function always includes core CSP terms, then adds any terms that appear in the model response.
 */
function getRelevantGlossaryTerms(take) {
    const text = [
        take.headline,
        take.market_mood,
        take.csp_stance,
        take.reasoned_take,
        take.csp_take,
        take.action,
        take.avoid,
        ...(take.scenarios || []),
        ...(take.company_notes || []).map(note => note.note),
    ].join(" ").toLowerCase();
    const alwaysUseful = ["assignment risk", "delta", "IV", "premium"];
    const matchedTerms = Object.keys(GLOSSARY).filter(term => text.includes(term.toLowerCase()));
    const terms = [...new Set([...matchedTerms, ...alwaysUseful])];

    return terms.slice(0, 8);
}

/** Explain the model's market-mood label in beginner language. */
/**
 * Explain a short market mood label in beginner-friendly language.
 * Mood labels are intentionally concise, so this helper adds just enough context to avoid buzzword confusion.
 */
function marketMoodExplanation(mood) {
    const explanations = {
        Calm: "Prices are moving more steadily, so fewer warning signs are showing up.",
        Mixed: "Some stocks look strong while others look weak, so stock selection matters.",
        Choppy: "Prices are bouncing around, so a good-looking premium can come with extra risk.",
        Risky: "The market setup looks unstable, so passing on trades may be reasonable.",
    };

    return explanations[mood] || "This describes the overall feel of the current market setup.";
}

/** Explain how selective the CSP scan should be. */
/**
 * Explain a short CSP stance label in beginner-friendly language.
 * This turns labels like Wait or Selective into actionable meaning inside the Market Take cards.
 */
function cspStanceExplanation(stance) {
    const explanations = {
        Favorable: "The setup looks reasonable for filtered CSP ideas, while still using position rules.",
        Selective: "Only the cleanest CSP candidates deserve attention right now.",
        Cautious: "Premium may look tempting, but risk deserves extra weight.",
        Wait: "The setup does not look clear enough to force CSP trades.",
    };

    return explanations[stance] || "This describes how aggressive the CSP search should be.";
}

/** Replace ticker mentions in escaped text with company tooltips. */
/**
 * Replace known ticker symbols in plain text with tooltip-enabled ticker spans.
 * AI summaries can mention symbols naturally, and this helper upgrades them into explainable UI elements.
 */
function annotateTickers(text) {
    const escaped = escapeHtml(text || "");
    const tickers = Object.keys(companyNames).sort((a, b) => b.length - a.length);

    if (!tickers.length) {
        return escaped;
    }

    const tickerPattern = new RegExp(`\\b(${tickers.join("|")})(?=\\b|\\d)`, "g");

    return escaped.replace(tickerPattern, match => tickerTooltip(match));
}
