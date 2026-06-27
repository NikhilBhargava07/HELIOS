/** Render API data into the recommendation, portfolio, market, and news panels. */

/** Render the agent's decision and selected-contract action. */
function renderReview(review) {
    const selectedContract = review.selected_contract;
    const selectedCandidate = selectedContract ? candidateByContract(selectedContract) : null;

    reviewEl.classList.remove("empty");
    reviewEl.innerHTML = `
        <div><span class="label">Decision:</span> ${formatDecision(review.decision)}</div>
        <div><span class="label">Selected:</span> ${annotateTickers(selectedContract || "None")}</div>
        <div><span class="label">Summary:</span> ${annotateTickers(review.summary)}</div>
        <div class="warning"><span class="label">Risk note:</span> ${annotateTickers(review.risk_note)}</div>
        ${selectedContract ? `
            <div class="review-actions">
                <button data-action="place_paper_order" data-contract="${escapeHtml(selectedContract)}">
                    Paper place selected${selectedCandidate ? ` (${tickerTooltip(selectedCandidate.tickerSymbol)} ${money(selectedCandidate.strike)} put)` : ""}
                </button>
            </div>
        ` : ""}
    `;
}

/** Initialize the visible and queued recommendation candidate lists. */
function renderCandidates(candidates) {
    candidatePool = candidates;
    visibleCandidates = candidatePool.slice(0, visibleCandidateLimit);
    queuedCandidates = candidatePool.slice(visibleCandidateLimit);
    renderVisibleCandidates();
}

/** Render the currently visible candidate cards and their actions. */
function renderVisibleCandidates() {
    if (!visibleCandidates.length) {
        candidateList.innerHTML = "<p>No candidates passed the filters.</p>";
        return;
    }

    candidateList.innerHTML = visibleCandidates.map(candidate => `
        <article class="candidate-card" data-contract="${candidate.contractSymbol}">
            <p class="eyebrow">Top candidate</p>
            <h3>Sell 1 ${tickerTooltip(candidate.tickerSymbol)} ${money(candidate.strike)} put</h3>
            <div class="stats">
                <div><span class="label">Expiration:</span> ${candidate.expiration} (${candidate.DTE} DTE)</div>
                <div><span class="label">Current price:</span> ${money(candidate.currentStockPrice)}</div>
                <div><span class="label">Delta:</span> ${Number(candidate.delta).toFixed(3)}</div>
                <div><span class="label">IV:</span> ${percent(candidate.ivPercent)}</div>
                <div><span class="label">Spread:</span> ${money(candidate.spread)}</div>
                <div><span class="label">Premium:</span> ${money(candidate.premiumIfSoldAtBid)}</div>
                <div><span class="label">Cash required:</span> ${money(candidate.cashRequired)}</div>
                <div><span class="label">Breakeven:</span> ${money(candidate.breakevenPrice)}</div>
                <div><span class="label">ROC:</span> ${percent(candidate.returnOnCashPercent)}</div>
            </div>
            <div class="actions">
                <button data-action="place_paper_order" data-contract="${candidate.contractSymbol}">
                    Paper place
                </button>
                <button class="secondary" data-action="discard" data-contract="${candidate.contractSymbol}">
                    Discard
                </button>
            </div>
        </article>
    `).join("");
}

/** Render live Alpaca positions, capital usage, and saved order history. */
function renderDashboard(dashboard) {
    if (!dashboard) {
        return;
    }

    const capital = dashboard.capital || dashboard;
    const positions = dashboard.open_positions || capital.open_positions || [];
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
            <div><span class="label">Total capital:</span> ${money(capital.total_capital)}</div>
            <div><span class="label">Max CSP capital:</span> ${money(capital.max_csp_capital)}</div>
            <div><span class="label">Committed:</span> ${money(capital.committed_capital)}</div>
            <div><span class="label">Available CSP capital:</span> ${money(capital.available_csp_capital)}</div>
            ${capital.effective_available_csp_capital !== undefined ? `
                <div><span class="label">Effective CSP cash:</span> ${money(capital.effective_available_csp_capital)}</div>
            ` : ""}
            <div><span class="label">Open positions:</span> ${capital.open_position_count}/${capital.max_open_positions}</div>
        </div>
        <h3>Open Positions</h3>
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
        `).join("") : "<p>No open paper positions.</p>"}
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
