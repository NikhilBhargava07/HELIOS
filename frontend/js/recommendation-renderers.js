/** Render API data into the recommendation, portfolio, market, and news panels. */

/**
 * Render the capital snapshot strip at the top of the recommendations page.
 * Showing available cash, committed capital, open slots, and buying power up front means exposure is visible before the user acts on any candidate.
 */
function renderRecsMetrics(dashboard) {
    const metricsEl = document.querySelector("#recs-metrics");

    if (!metricsEl || !dashboard) {
        return;
    }

    const capital = dashboard.capital || {};
    const account = dashboard.account || {};
    const available = capital.effective_available_csp_capital ?? capital.available_csp_capital ?? 0;
    const buyingPower = account.options_buying_power ?? account.buying_power ?? capital.total_capital ?? 0;

    metricsEl.classList.remove("empty");
    metricsEl.innerHTML = `
        <div class="rec-metric"><span class="rec-lbl">Available CSP cash</span><span class="num">${money(available)}</span></div>
        <div class="rec-metric"><span class="rec-lbl">Committed</span><span class="num">${money(capital.committed_capital ?? 0)}</span></div>
        <div class="rec-metric"><span class="rec-lbl">Open CSPs</span><span class="num">${capital.open_position_count ?? 0}<span class="rec-metric-sub"> / ${capital.max_open_positions ?? 5}</span></span></div>
        <div class="rec-metric"><span class="rec-lbl">Buying power</span><span class="num">${money(buyingPower)}</span></div>
    `;
}

/**
 * Render the agent review banner: decision, selected contract, summary, and the hard risk note.
 * The AI's selection is remembered so the candidate list can feature the same contract the agent chose.
 */
function renderReview(review) {
    if (!review) {
        reviewEl.classList.add("empty");
        reviewEl.textContent = "Run the scan to see the agent's recommendation.";
        return;
    }

    recommendedContract = review.selected_contract || null;
    const hasSelection = Boolean(review.selected_contract);

    reviewEl.classList.remove("empty");
    reviewEl.innerHTML = `
        <div class="rec-review-head">
            <span class="rec-lbl">Agent review</span>
            <span class="rec-badge ${hasSelection ? "approve" : "reject"}">${formatDecision(review.decision)}</span>
            ${hasSelection ? `<span class="rec-review-sel num">${annotateTickers(review.selected_contract)}</span>` : ""}
            ${hasSelection ? `
                <button class="rec-review-place" data-action="place_paper_order" data-contract="${escapeHtml(review.selected_contract)}">Paper place</button>
            ` : ""}
        </div>
        <p class="rec-review-summary">${annotateTickers(review.summary)}</p>
        <div class="rec-review-risk"><span class="rec-risk-tag">Risk</span> ${annotateTickers(review.risk_note)}</div>
    `;
}

/**
 * Store the ranked candidate pool for the current run and render the featured/alternate layout.
 * The agent's selected contract is promoted to the front so it appears as the featured recommendation.
 */
function renderCandidates(candidates, selectedContract = recommendedContract) {
    candidatePool = orderByRecommended(candidates || [], selectedContract);
    renderRecsCandidates();
}

/**
 * Move the agent-selected contract to the front of the candidate list.
 * This keeps the featured card aligned with the agent's pick without discarding the backend's overall ranking of the rest.
 */
function orderByRecommended(candidates, selectedContract) {
    const ordered = candidates.slice();

    if (!selectedContract) {
        return ordered;
    }

    const index = ordered.findIndex(candidate => candidate.contractSymbol === selectedContract);

    if (index > 0) {
        const [picked] = ordered.splice(index, 1);
        ordered.unshift(picked);
    }

    return ordered;
}

/**
 * Render the featured recommendation plus a row of swappable alternate candidates.
 * The first pool entry is featured; the next few are shown compactly so the user can pick a different name without discarding.
 */
function renderRecsCandidates() {
    if (!candidatePool.length) {
        candidateList.innerHTML = `<p class="rec-empty">No candidates passed the filters.</p>`;
        return;
    }

    const featured = candidatePool[0];
    const alternates = candidatePool.slice(1, 1 + MAX_ALTERNATES);

    candidateList.innerHTML = `
        ${renderFeaturedCandidate(featured)}
        ${alternates.length ? renderAlternates(alternates) : ""}
    `;
}

/**
 * Render the featured CSP card with the practical numbers needed before paper placing.
 * Premium, return on cash, and delta are promoted as hero stats; the remaining details stay in a quiet aligned row.
 */
function renderFeaturedCandidate(candidate) {
    return `
        <article class="rec-featured" data-contract="${candidate.contractSymbol}">
            <div class="rec-featured-top">
                <div class="rec-featured-title">
                    <p class="rec-eyebrow">Recommended</p>
                    <h3>Sell 1 ${tickerTooltip(candidate.tickerSymbol)} $${Number(candidate.strike)} put</h3>
                    <p class="rec-sub">${escapeHtml(companyNameForTicker(candidate.tickerSymbol))} · ${escapeHtml(candidate.expiration)} · ${candidate.DTE} DTE</p>
                </div>
                <div class="rec-featured-price">
                    <span class="rec-lbl">Underlying</span>
                    <span class="num">${money(candidate.currentStockPrice)}</span>
                </div>
            </div>
            <div class="rec-hero-stats">
                <div class="rec-hero-stat"><span class="rec-lbl">Premium</span><span class="num rec-pos">${money(candidate.premiumIfSoldAtBid)}</span></div>
                <div class="rec-hero-stat"><span class="rec-lbl">Return on cash</span><span class="num">${percent(candidate.returnOnCashPercent)}</span></div>
                <div class="rec-hero-stat"><span class="rec-lbl">Delta</span><span class="num">${Number(candidate.delta).toFixed(2)}</span></div>
            </div>
            <div class="rec-detail-row">
                <span class="rec-lbl">IV<span class="num">${percent(candidate.ivPercent)}</span></span>
                <span class="rec-lbl">Spread<span class="num">${money(candidate.spread)}</span></span>
                <span class="rec-lbl">Cash required<span class="num">${money(candidate.cashRequired)}</span></span>
                <span class="rec-lbl">Breakeven<span class="num">${money(candidate.breakevenPrice)}</span></span>
            </div>
            <div class="rec-actions">
                <button data-action="place_paper_order" data-contract="${candidate.contractSymbol}">Paper place</button>
                <button class="rec-ghost" data-action="discard" data-contract="${candidate.contractSymbol}">Discard</button>
            </div>
        </article>
    `;
}

/**
 * Render the alternate-candidate row shown beneath the featured recommendation.
 * Discarding the featured card promotes the next candidate here, and "Swap in" lets the user feature a different name directly.
 */
function renderAlternates(alternates) {
    return `
        <div class="rec-alts">
            <div class="rec-alts-head">
                <span class="rec-lbl">More candidates</span>
                <span class="rec-hint">hover or tap for detail</span>
            </div>
            <div class="rec-alts-grid">
                ${alternates.map(renderAlternateCard).join("")}
            </div>
        </div>
    `;
}

/**
 * Render one compact alternate-candidate card that reveals full detail on hover, tap, or focus.
 * The headline numbers stay visible; the expanding panel adds IV, spread, cash, and breakeven plus place/discard actions, so a candidate can be reviewed and placed without leaving the row.
 */
function renderAlternateCard(candidate) {
    return `
        <article class="rec-alt" data-contract="${candidate.contractSymbol}" tabindex="0">
            <div class="rec-alt-top">
                <span class="rec-alt-name">${tickerTooltip(candidate.tickerSymbol)} $${Number(candidate.strike)}P</span>
                <span class="rec-lbl num">${candidate.DTE}d</span>
            </div>
            <div class="rec-alt-stats">
                <span class="rec-lbl">Prem<span class="num rec-pos">${money(candidate.premiumIfSoldAtBid)}</span></span>
                <span class="rec-lbl">ROC<span class="num">${percent(candidate.returnOnCashPercent)}</span></span>
                <span class="rec-lbl">&Delta;<span class="num">${Number(candidate.delta).toFixed(2)}</span></span>
            </div>
            <div class="rec-alt-detail">
                <div class="rec-alt-detail-grid">
                    <span class="rec-lbl">IV<span class="num">${percent(candidate.ivPercent)}</span></span>
                    <span class="rec-lbl">Spread<span class="num">${money(candidate.spread)}</span></span>
                    <span class="rec-lbl">Cash<span class="num">${money(candidate.cashRequired)}</span></span>
                    <span class="rec-lbl">Breakeven<span class="num">${money(candidate.breakevenPrice)}</span></span>
                </div>
                <div class="rec-alt-actions">
                    <button data-action="place_paper_order" data-contract="${candidate.contractSymbol}">Paper place</button>
                    <button class="rec-ghost" data-action="discard" data-contract="${candidate.contractSymbol}">Discard</button>
                </div>
            </div>
        </article>
    `;
}

/**
 * Render live Alpaca capital, positions, and active paper orders.
 * The dashboard explains whether data came from Alpaca or memory and separates CSP exposure from regular stock or other positions.
 */
function renderDashboard(dashboard) {
    if (!dashboard) {
        return;
    }

    const capital = dashboard.capital || dashboard;
    const account = dashboard.account || {};
    const positions = dashboard.open_positions || capital.open_positions || [];
    const stockPositions = dashboard.stock_positions || [];
    const orders = dashboard.paper_orders || [];
    const visibleOrders = orders.filter(order => {
        const status = String(order.status || "").toLowerCase();
        return status !== "canceled" && status !== "cancelled";
    });

    dashboardEl.classList.remove("empty");
    dashboardEl.innerHTML = `
        <p class="ledger-note">
            ${dashboard.position_source === "alpaca"
                ? "Open positions, buying power, and order statuses are synced from Alpaca paper trading. Decisions and history are saved in HELIOS memory."
                : "Alpaca positions could not be loaded, so open positions are temporarily shown from saved HELIOS memory."}
        </p>
        <div class="dashboard-grid">
            <div><span class="label">Alpaca equity:</span> ${money(account.portfolio_value ?? capital.total_capital)}</div>
            <div><span class="label">Alpaca cash:</span> ${money(account.cash)}</div>
            <div><span class="label">Options buying power:</span> ${money(account.options_buying_power ?? account.buying_power)}</div>
            <div><span class="label">Max CSP capital:</span> ${money(capital.max_csp_capital)}</div>
            <div><span class="label">CSP committed:</span> ${money(capital.committed_capital)}</div>
            <div><span class="label">Available CSP capital:</span> ${money(capital.available_csp_capital)}</div>
            ${capital.effective_available_csp_capital !== undefined ? `
                <div><span class="label">Effective CSP cash:</span> ${money(capital.effective_available_csp_capital)}</div>
            ` : ""}
            <div><span class="label">Open CSPs:</span> ${capital.open_position_count}/${capital.max_open_positions}</div>
            ${capital.total_open_position_count !== undefined ? `
                <div><span class="label">Total Alpaca positions:</span> ${capital.total_open_position_count}</div>
            ` : ""}
        </div>
        <h3>Open CSP Positions</h3>
        ${positions.length ? positions.map(position => `
            <div class="history-row">
                <strong>${tickerTooltip(position.ticker_symbol)} ${money(position.strike)} CSP</strong> ·
                ${position.quantity !== undefined ? `Quantity ${Number(position.quantity)} · ` : ""}
                ${position.expiration ? `Expires ${escapeHtml(position.expiration)} · ` : ""}
                Cash ${money(position.cash_required)} ·
                Premium ${money(position.premium_received)}
                ${position.breakeven_price !== undefined ? ` · Breakeven ${money(position.breakeven_price)}` : ""}
                ${position.market_value !== undefined && position.market_value !== null ? ` · Market value ${money(position.market_value)}` : ""}
                ${position.unrealized_pnl !== undefined && position.unrealized_pnl !== null ? ` · Unrealized P&amp;L ${signedMoney(position.unrealized_pnl)}` : ""}
            </div>
        `).join("") : "<p>No open CSP positions.</p>"}
        <h3>Stock / Other Positions</h3>
        ${stockPositions.length ? stockPositions.map(position => `
            <div class="history-row">
                <strong>${tickerTooltip(position.ticker_symbol)}</strong> ·
                ${position.asset_class ? `${escapeHtml(String(position.asset_class))} · ` : ""}
                ${position.quantity !== undefined && position.quantity !== null ? `Quantity ${Number(position.quantity)} · ` : ""}
                ${position.average_entry_price !== undefined && position.average_entry_price !== null ? `Avg entry ${money(position.average_entry_price)} · ` : ""}
                ${position.current_price !== undefined && position.current_price !== null ? `Current ${money(position.current_price)} · ` : ""}
                ${position.market_value !== undefined && position.market_value !== null ? `Market value ${money(position.market_value)} · ` : ""}
                ${position.unrealized_pnl !== undefined && position.unrealized_pnl !== null ? `Unrealized P&amp;L ${signedMoney(position.unrealized_pnl)}` : ""}
            </div>
        `).join("") : "<p>No stock or other open positions.</p>"}
        <h3>Recent Paper Orders</h3>
        ${visibleOrders.length ? visibleOrders.slice().reverse().map(order => `
            <div class="history-row">
                <strong>${orderStatusText(order)}:</strong>
                Sell-to-open ${tickerTooltip(order.ticker_symbol)} ${money(order.strike)} put ·
                ${orderCreditText(order)}
            </div>
        `).join("") : "<p>No active paper orders.</p>"}
    `;
}
