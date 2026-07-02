/** Format values and build small, reusable HTML fragments safely. */

/** Format a numeric value as US currency. */
function money(value) {
    return `$${Number(value).toLocaleString(undefined, {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
    })}`;
}

/** Find a loaded candidate by its OCC contract symbol. */
function candidateByContract(contractSymbol) {
    return candidatePool.find(candidate => candidate.contractSymbol === contractSymbol);
}

/** Check whether available cash fully secures a candidate. */
function candidateIsAffordable(candidate, availableCash) {
    if (availableCash === null || availableCash === undefined) {
        return true;
    }

    return Number(candidate.cashRequired || 0) <= Number(availableCash);
}

/** Remove candidates that exceed current effective CSP cash. */
function filterAffordableCandidates(candidates, availableCash) {
    return (candidates || []).filter(candidate => candidateIsAffordable(candidate, availableCash));
}

/** Check whether the AI selection remains in the affordable candidate list. */
function selectedContractIsAffordable(review, candidates) {
    if (!review?.selected_contract) {
        return false;
    }

    return candidates.some(candidate => candidate.contractSymbol === review.selected_contract);
}

/** Replace an unaffordable AI selection with a safe display decision. */
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

/** Display a temporary success or failure notification. */
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

/** Format a percentage without forcing a sign. */
function percent(value) {
    if (value === null || value === undefined) {
        return "n/a";
    }

    return `${Number(value).toFixed(2)}%`;
}

/** Format a percentage with its positive or negative direction. */
function signedPercent(value) {
    if (value === null || value === undefined) {
        return "n/a";
    }

    const number = Number(value);
    const sign = number > 0 ? "+" : "";

    return `${sign}${number.toFixed(2)}%`;
}

/** Format a currency change with its positive or negative direction. */
function signedMoney(value) {
    if (value === null || value === undefined) {
        return "n/a";
    }

    const number = Number(value);
    const sign = number > 0 ? "+" : number < 0 ? "-" : "";

    return `${sign}${money(Math.abs(number))}`;
}

/** Select the CSS class for positive, negative, or neutral movement. */
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

/** Build one rotating percentage/dollar trend row. */
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

/** Format a price while handling unavailable quotes. */
function priceText(value) {
    if (value === null || value === undefined) {
        return "Price n/a";
    }

    return money(value);
}

/** Format an RSS timestamp into a compact news-card date. */
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

/** Resolve a ticker to its display company name. */
function companyNameForTicker(ticker) {
    return companyNames[ticker] || ticker;
}

/** Render a ticker with a keyboard-accessible company-name tooltip. */
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

/** Convert backend decision identifiers into title-cased text. */
function formatDecision(value) {
    return String(value || "")
        .replaceAll("_", " ")
        .replace(/\b\w/g, letter => letter.toUpperCase());
}

/** Describe whether an order filled, was canceled, or is still pending. */
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

/** Return the actual fill price or requested limit credit per share. */
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

/** Escape untrusted text before inserting it into HTML templates. */
function escapeHtml(value) {
    return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
}

/** Allow only HTTP(S) links from external news content. */
function safeExternalUrl(value) {
    try {
        const url = new URL(String(value || ""));
        return ["http:", "https:"].includes(url.protocol) ? url.href : "#";
    } catch {
        return "#";
    }
}

/** Render one glossary term and its explanatory tooltip. */
function glossaryTerm(term) {
    return `
        <span class="tooltip-term" tabindex="0">
            ${escapeHtml(term)}
            <span class="tooltip-bubble">${escapeHtml(GLOSSARY[term])}</span>
        </span>
    `;
}

/** Render a list of glossary terms as compact chips. */
function renderGlossaryChips(terms) {
    return terms.map(term => `
        <span class="glossary-chip">
            ${glossaryTerm(term)}
        </span>
    `).join("");
}

/** Select glossary terms that appear in or help explain an AI take. */
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
function annotateTickers(text) {
    const escaped = escapeHtml(text || "");
    const tickers = Object.keys(companyNames).sort((a, b) => b.length - a.length);

    if (!tickers.length) {
        return escaped;
    }

    const tickerPattern = new RegExp(`\\b(${tickers.join("|")})(?=\\b|\\d)`, "g");

    return escaped.replace(tickerPattern, match => tickerTooltip(match));
}
