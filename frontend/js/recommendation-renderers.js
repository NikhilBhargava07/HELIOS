/** Render API data into the recommendation, portfolio, market, and news panels. */

/**
 * Render the capital snapshot strip at the top of the recommendations page.
 * Showing available cash, committed capital, open slots, and buying power up front means exposure is visible before the user acts on any candidate.
 */
function renderRecsMetrics(data) {
    const metricsEl = document.querySelector("#recs-metrics");

    if (!metricsEl || !data?.dashboard) {
        return;
    }

    // Each strategy is limited by a different thing, so each states its own: cash secures a
    // put, shares make a covered call possible, and buying stock just spends money.
    metricsEl.classList.remove("empty");
    metricsEl.innerHTML = strategyView(currentStrategyKey).metrics(data).map(metric => `
        <div class="rec-metric">
            <span class="rec-lbl">${escapeHtml(metric.label)}</span>
            <span class="num">${escapeHtml(String(metric.value))}${metric.suffix ? `<span class="rec-metric-sub">${escapeHtml(metric.suffix)}</span>` : ""}</span>
            ${metric.hint ? `<span class="rec-metric-hint">${escapeHtml(metric.hint)}</span>` : ""}
        </div>
    `).join("");
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
            ${hasSelection && strategyView(currentStrategyKey).canPlace ? `
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

    const index = ordered.findIndex(candidate => candidateId(candidate) === selectedContract);

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
 * Render the featured card with the practical numbers needed before acting on it.
 * The active strategy's view decides the headline, which numbers lead, and whether placing is offered at all.
 */
function renderFeaturedCandidate(candidate) {
    const view = strategyView(currentStrategyKey);
    const id = view.idOf(candidate);

    return `
        <article class="rec-featured" data-contract="${escapeHtml(id)}">
            <div class="rec-featured-top">
                <div>
                    <p class="rec-eyebrow">Recommended</p>
                    <h3>${view.headline(candidate)}</h3>
                    <p class="rec-sub">${view.subline(candidate)}</p>
                </div>
                ${view.underlyingLabel ? `
                    <div class="rec-featured-price">
                        <span class="rec-lbl">${view.underlyingLabel}</span>
                        <span class="num">${money(candidate.currentStockPrice)}</span>
                    </div>
                ` : ""}
            </div>
            <div class="rec-hero-stats">
                ${view.heroStats(candidate).map(renderHeroStat).join("")}
            </div>
            <div class="rec-detail-row">
                ${view.details(candidate).map(renderDetailStat).join("")}
            </div>
            ${view.advisoryNote ? `<p class="rec-advisory">${escapeHtml(view.advisoryNote)}</p>` : ""}
            <div class="rec-actions">
                ${view.canPlace ? `<button data-action="place_paper_order" data-contract="${escapeHtml(id)}">Paper place</button>` : ""}
                <button class="rec-ghost" data-action="discard" data-contract="${escapeHtml(id)}">Discard</button>
            </div>
        </article>
    `;
}

/** Render one leading stat for a candidate card. */
function renderHeroStat(stat) {
    return `<div class="rec-hero-stat"><span class="rec-lbl">${stat.label}</span><span class="num ${stat.tone || ""}">${stat.value}</span></div>`;
}

/** Render one secondary stat in a card's quiet aligned row. */
function renderDetailStat(stat) {
    return `<span class="rec-lbl">${stat.label}<span class="num ${stat.tone || ""}">${stat.value}</span></span>`;
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
    const view = strategyView(currentStrategyKey);
    const id = view.idOf(candidate);

    return `
        <article class="rec-alt" data-contract="${escapeHtml(id)}" tabindex="0">
            <div class="rec-alt-top">
                <span class="rec-alt-name">${view.shortName(candidate)}</span>
                <span class="rec-lbl num">${view.shortMeta(candidate)}</span>
            </div>
            <div class="rec-alt-stats">
                ${view.compactStats(candidate).map(renderDetailStat).join("")}
            </div>
            <div class="rec-alt-detail">
                <div class="rec-alt-detail-grid">
                    ${view.details(candidate).map(renderDetailStat).join("")}
                </div>
                <div class="rec-alt-actions">
                    ${view.canPlace ? `<button data-action="place_paper_order" data-contract="${escapeHtml(id)}">Paper place</button>` : ""}
                    <button class="rec-ghost" data-action="discard" data-contract="${escapeHtml(id)}">Discard</button>
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

    const equity = account.portfolio_value ?? capital.total_capital;
    const buyingPower = account.options_buying_power ?? account.buying_power;
    const maxCsp = Number(capital.max_csp_capital) || 0;
    const committed = Number(capital.committed_capital) || 0;
    const available = capital.effective_available_csp_capital ?? capital.available_csp_capital;
    const committedPct = maxCsp > 0 ? Math.min(100, Math.round((committed / maxCsp) * 100)) : 0;
    const isLive = dashboard.position_source === "alpaca";

    dashboardEl.classList.remove("empty");
    dashboardEl.innerHTML = `
        <div class="cap-source ${isLive ? "live" : "memory"}">
            ${isLive
                ? "Synced from Alpaca paper trading · decisions saved in HELIOS memory"
                : "Alpaca unavailable · showing saved HELIOS memory"}
        </div>
        <div class="cap-kpis">
            <div class="cap-kpi"><span class="cap-lbl">Equity</span><span class="num">${money(equity)}</span></div>
            <div class="cap-kpi"><span class="cap-lbl">Cash</span><span class="num">${money(account.cash)}</span></div>
            <div class="cap-kpi"><span class="cap-lbl">Options buying power</span><span class="num">${money(buyingPower)}</span></div>
            <div class="cap-kpi"><span class="cap-lbl">Open CSPs</span><span class="num">${capital.open_position_count ?? 0}<span class="cap-kpi-sub"> / ${capital.max_open_positions ?? 5}</span></span></div>
        </div>
        <div class="cap-alloc">
            <div class="cap-alloc-head">
                <span class="cap-lbl">CSP capital allocation</span>
                <span class="num cap-alloc-meta">${money(committed)} committed · ${money(maxCsp)} max</span>
            </div>
            <div class="cap-alloc-bar"><div class="cap-alloc-fill" style="width:${committedPct}%"></div></div>
            <div class="cap-alloc-foot">
                <span class="num cap-alloc-committed">committed ${committedPct}%</span>
                <span class="num cap-lbl">available ${available !== undefined && available !== null ? money(available) : "—"}</span>
            </div>
        </div>
        <h3 class="cap-h">Open CSP positions</h3>
        ${positions.length ? `
            <table class="cap-table">
                <thead><tr><th>Position</th><th>Expires</th><th class="cap-r">Premium</th><th class="cap-r">Cash</th><th class="cap-r">Unreal. P&amp;L</th></tr></thead>
                <tbody>
                    ${positions.map(position => `
                        <tr>
                            <td>${tickerTooltip(position.ticker_symbol)} <span class="num">${money(position.strike)} put</span></td>
                            <td class="num cap-muted">${position.expiration ? escapeHtml(position.expiration) : "—"}</td>
                            <td class="num cap-r">${money(position.premium_received)}</td>
                            <td class="num cap-r">${money(position.cash_required)}</td>
                            <td class="num cap-r">${pnlCell(position.unrealized_pnl)}</td>
                        </tr>
                    `).join("")}
                </tbody>
            </table>
        ` : `<p class="cap-empty">No open CSP positions.</p>`}
        ${stockPositions.length ? `
            <h3 class="cap-h">Stock / other positions</h3>
            <table class="cap-table">
                <thead><tr><th>Position</th><th class="cap-r">Qty</th><th class="cap-r">Avg entry</th><th class="cap-r">Current</th><th class="cap-r">Unreal. P&amp;L</th></tr></thead>
                <tbody>
                    ${stockPositions.map(position => `
                        <tr>
                            <td>${tickerTooltip(position.ticker_symbol)}${position.asset_class ? ` <span class="cap-muted">${escapeHtml(String(position.asset_class))}</span>` : ""}</td>
                            <td class="num cap-r">${position.quantity !== undefined && position.quantity !== null ? Number(position.quantity) : "—"}</td>
                            <td class="num cap-r">${position.average_entry_price !== undefined && position.average_entry_price !== null ? money(position.average_entry_price) : "—"}</td>
                            <td class="num cap-r">${position.current_price !== undefined && position.current_price !== null ? money(position.current_price) : "—"}</td>
                            <td class="num cap-r">${pnlCell(position.unrealized_pnl)}</td>
                        </tr>
                    `).join("")}
                </tbody>
            </table>
        ` : ""}
        <h3 class="cap-h">Recent paper orders</h3>
        ${visibleOrders.length ? `
            <div class="cap-orders">
                ${visibleOrders.slice().reverse().map(order => `
                    <div class="cap-order">
                        <span class="cap-badge ${orderBadgeClass(order)}">${orderShortStatus(order)}</span>
                        <span class="cap-order-desc">Sell-to-open ${tickerTooltip(order.ticker_symbol)} <span class="num">${money(order.strike)} put</span></span>
                        <span class="num cap-order-credit">${orderCreditText(order)}</span>
                    </div>
                `).join("")}
            </div>
        ` : `<p class="cap-empty">No active paper orders.</p>`}
    `;
}

/**
 * Render an unrealized P&L cell with directional color, or a muted dash when the broker omits it.
 * Keeps the positions tables aligned and lets gains and losses read at a glance.
 */
function pnlCell(value) {
    if (value === undefined || value === null) {
        return `<span class="cap-muted">&mdash;</span>`;
    }

    const number = Number(value);
    const directionClass = number > 0 ? "cap-pos" : number < 0 ? "cap-neg" : "";
    return `<span class="${directionClass}">${signedMoney(value)}</span>`;
}

/**
 * Map an order status to a compact badge color class.
 * Filled reads positive, terminal states read negative, and everything else is a pending amber.
 */
function orderBadgeClass(order) {
    const status = String(order.status || "").toLowerCase();

    if (status === "filled") {
        return "filled";
    }

    if (["canceled", "cancelled", "expired", "rejected"].includes(status)) {
        return "rejected";
    }

    return "pending";
}

/**
 * Produce a short, badge-friendly status label for a paper order.
 * The longer "awaiting fill" phrasing stays out of the badge so the row stays compact.
 */
function orderShortStatus(order) {
    const status = String(order.status || "unknown").toLowerCase();

    if (status === "filled") {
        return "Filled";
    }

    if (["canceled", "cancelled"].includes(status)) {
        return "Canceled";
    }

    if (status === "expired") {
        return "Expired";
    }

    if (status === "rejected") {
        return "Rejected";
    }

    return "Awaiting fill";
}
