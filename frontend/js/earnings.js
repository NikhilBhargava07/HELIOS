/**
 * Show when each approved company reports, and how its last report landed.
 *
 * The table exists to be consulted while judging a recommendation: a contract running
 * thirty to forty-five days almost always spans a quarterly report, and a price move
 * means something different before one than after it. Rows are ordered by how soon the
 * next report is, because "what is coming up" is the question being asked.
 *
 * Funds are absent rather than listed empty. A fund holds companies instead of being
 * one, so it has no report of its own, and the page says so rather than looking short.
 */

const EARNINGS_PAGE_SIZE = 12;
const EARNINGS_SOON_DAYS = 7;

/** Load the stored earnings calendar and draw the table. */
async function loadEarnings() {
    if (!earningsList || !isSignedIn()) {
        return;
    }

    earningsStatus.textContent = "Loading earnings calendar...";

    try {
        const response = await apiFetch("/api/market/earnings", { auth: true });

        if (!response.ok) {
            throw new Error(await brokerErrorMessage(response, `Request failed with status ${response.status}`));
        }

        const data = await response.json();
        latestEarnings = data.earnings || [];
        companyNames = data.company_names || companyNames;
        excludedFunds = data.excluded_funds || [];
        renderEarnings();

        earningsStatus.textContent = latestEarnings.length
            ? `${latestEarnings.length} companies. Funds are not listed because they do not report earnings.`
            : "No earnings data yet. It loads once the calendar has been refreshed.";
    } catch (error) {
        earningsStatus.textContent = `Error: ${error.message}`;
    }
}

/** Apply the current search and filter, then draw the visible rows. */
function renderEarnings() {
    if (!latestEarnings.length) {
        earningsList.classList.add("empty");
        earningsList.innerHTML = "No earnings data has been loaded yet.";
        toggleEarningsButton.classList.add("hidden");
        return;
    }

    const matching = filteredEarnings();
    const visible = showAllEarnings ? matching : matching.slice(0, EARNINGS_PAGE_SIZE);

    earningsList.classList.remove("empty");
    earningsList.innerHTML = `
        <div class="earnings-controls">
            <input id="earnings-search" class="earnings-search" type="search" autocomplete="off"
                   placeholder="Search a company or ticker" value="${escapeHtml(earningsSearch)}" />
            <div class="earnings-filters">
                ${["All", "Reporting soon", "Already reported", "Mega-tech", "Financials", "Consumer"].map(filter => `
                    <button type="button" class="trend-pill ${filter === earningsFilter ? "active" : ""}" data-earnings-filter="${escapeHtml(filter)}">${filter}</button>
                `).join("")}
            </div>
        </div>
        ${visible.length ? `
            <div class="earnings-head">
                <span>Company</span>
                <span>Last reported</span>
                <span>Result</span>
                <span>Next report</span>
                <span>Projected</span>
            </div>
            ${visible.map(renderEarningsRow).join("")}
        ` : `<p class="earnings-empty">No company matches that search.</p>`}
    `;

    toggleEarningsButton.classList.toggle("hidden", matching.length <= EARNINGS_PAGE_SIZE);
    toggleEarningsButton.textContent = showAllEarnings ? "Show fewer" : `Show all ${matching.length}`;
}

/** Narrow the table by the search box and the selected filter. */
function filteredEarnings() {
    const term = earningsSearch.trim().toLowerCase();
    let rows = latestEarnings;

    if (term) {
        rows = rows.filter(row =>
            String(row.ticker_symbol || "").toLowerCase().includes(term)
            || String(companyNameForTicker(row.ticker_symbol) || "").toLowerCase().includes(term));
    }

    if (earningsFilter === "Reporting soon") {
        return rows.filter(row => row.days_until_next_report !== null
            && row.days_until_next_report !== undefined
            && Number(row.days_until_next_report) <= EARNINGS_SOON_DAYS);
    }

    if (earningsFilter === "Already reported") {
        return rows.filter(row => row.last_reported_on);
    }

    // The remaining filters reuse the ticker groups the Trends page already defines.
    if (TREND_CATEGORIES[earningsFilter]) {
        const allowed = new Set(TREND_CATEGORIES[earningsFilter]);
        return rows.filter(row => allowed.has(row.ticker_symbol));
    }

    return rows;
}

/** Render one company's row: what it last posted, and when it reports next. */
function renderEarningsRow(row) {
    const days = row.days_until_next_report;
    const soon = days !== null && days !== undefined && Number(days) <= EARNINGS_SOON_DAYS;

    return `
        <article class="earnings-row ${soon ? "soon" : ""}">
            <span class="earnings-company">
                <span class="earnings-sym">${tickerTooltip(row.ticker_symbol)}</span>
                <span class="earnings-name">${escapeHtml(companyNameForTicker(row.ticker_symbol))}</span>
            </span>
            <span class="num">${escapeHtml(dateText(row.last_reported_on))}</span>
            <span class="num">${resultText(row)}</span>
            <span class="num">${escapeHtml(dateText(row.next_report_on))}${soon ? ` <span class="earnings-soon">in ${days}d</span>` : ""}</span>
            <span class="num">${escapeHtml(epsText(row.next_eps_estimate))}</span>
        </article>
    `;
}

/**
 * Show the last result against what was expected, coloured by which way it went.
 * A figure on its own says little; the gap to the estimate is the part worth reading.
 */
function resultText(row) {
    const actual = row.last_eps_actual;
    const estimate = row.last_eps_estimate;

    if (actual === null || actual === undefined) {
        return "&mdash;";
    }

    if (estimate === null || estimate === undefined) {
        return escapeHtml(epsText(actual));
    }

    const beat = Number(actual) >= Number(estimate);
    return `${escapeHtml(epsText(actual))} <span class="earnings-vs ${beat ? "rec-pos" : "rec-neg"}">vs ${escapeHtml(epsText(estimate))}</span>`;
}

/** Format earnings per share, or an em dash when the figure is unknown. */
function epsText(value) {
    if (value === null || value === undefined || Number.isNaN(Number(value))) {
        return "—";
    }

    const number = Number(value);
    return `${number < 0 ? "-" : ""}$${Math.abs(number).toFixed(2)}`;
}

/** Format a report date, or an em dash when none is known. */
function dateText(value) {
    if (!value) {
        return "—";
    }

    try {
        return new Date(`${value}T12:00:00Z`).toLocaleDateString([], { month: "short", day: "numeric" });
    } catch (error) {
        return String(value);
    }
}
