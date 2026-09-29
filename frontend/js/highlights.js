/**
 * Show what HELIOS found on its own today, and let the user act on one of those picks.
 *
 * A pick is a lead, not a live order. It was chosen hours ago against prices that have
 * since moved, so nothing here can be placed directly: acting on one re-scans that single
 * ticker first, and only a candidate that still passes today's rules gets a place button.
 * That keeps the freshness rule intact instead of widening it for convenience.
 */

const SLOT_LABELS = {
    open: "At the open",
    midday: "Midday",
    preclose: "Before the close",
};

/** Read today's automatic picks and render them above the manual scan area. */
async function loadDailyHighlights() {
    if (!highlightsEl || !isSignedIn()) {
        return;
    }

    try {
        const response = await apiFetch("/api/recommendations/highlights", { auth: true });
        if (!response.ok) {
            return;
        }

        const data = await response.json();
        renderDailyHighlights(data.highlights || []);
    } catch (error) {
        // A missing panel should never take the page down with it.
        highlightsEl.classList.add("hidden");
    }
}

/** Draw every slot that ran today, newest first, with its picks. */
function renderDailyHighlights(highlights) {
    const withPicks = highlights.filter(highlight => (highlight.picks || []).length);

    if (!highlights.length) {
        highlightsEl.classList.add("hidden");
        return;
    }

    latestHighlights = highlights;
    highlightsEl.classList.remove("hidden");

    // Every slot can legitimately find nothing, and saying so is more useful than hiding the panel.
    if (!withPicks.length) {
        const latest = highlights[highlights.length - 1];
        highlightsEl.innerHTML = `
            <div class="dh-head">
                <span class="dh-title">Nothing met the bar today</span>
                <span class="dh-sub">${highlights.length} automatic scan${highlights.length === 1 ? "" : "s"} so far</span>
            </div>
            <p class="dh-empty">${annotateTickers(latest.market_read || "No candidate stood out.")}</p>
        `;
        return;
    }

    highlightsEl.innerHTML = `
        <div class="dh-head">
            <span class="dh-title">Found while you were away</span>
            <span class="dh-sub">prices have moved since, so each is re-checked before it can be placed</span>
        </div>
        ${withPicks.slice().reverse().map(renderHighlightSlot).join("")}
    `;
}

/**
 * Render one scan as its own block: when it ran, what it read, and what it picked.
 * Each scan is a separate moment in the day, so it gets a header band and its own
 * outline rather than a hairline rule that let the day read as one long column.
 */
function renderHighlightSlot(highlight) {
    const picks = highlight.picks || [];

    return `
        <article class="dh-slot">
            <header class="dh-slot-head">
                <span class="dh-slot-badge">${escapeHtml(SLOT_LABELS[highlight.slot] || highlight.slot)}</span>
                <span class="dh-time">${escapeHtml(localTimeOf(highlight.created_at))}</span>
                <span class="dh-count">${picks.length} pick${picks.length === 1 ? "" : "s"}</span>
            </header>
            <p class="dh-read">${annotateTickers(highlight.market_read || "")}</p>
            <div class="dh-picks">
                ${picks.map(renderHighlightPick).join("")}
            </div>
            ${highlight.passed_over ? `
                <details class="dh-passed">
                    <summary>What it passed over</summary>
                    <p>${annotateTickers(highlight.passed_over)}</p>
                </details>
            ` : ""}
        </article>
    `;
}


/**
 * Render one pick so it can be judged at a glance, with the reasoning a click away.
 *
 * Collapsed, a pick is a headline, its trade type, and the one risk that matters,
 * because that is enough to decide whether to look closer. The full reasoning stays
 * available rather than being cut, since it is what makes an hours-old idea safe to
 * act on, but showing all of it at once turned the day into a wall of grey text.
 */
function renderHighlightPick(pick) {
    const view = strategyView(pick.strategy_key);

    return `
        <article class="dh-pick" data-identifier="${escapeHtml(pick.identifier)}" data-strategy="${escapeHtml(pick.strategy_key)}">
            <div class="dh-pick-top">
                <span class="dh-tag">${escapeHtml(view.label)}</span>
                <span class="dh-contract">${escapeHtml(pick.identifier)}</span>
            </div>
            <h4 class="dh-headline">${annotateTickers(pick.headline || pick.identifier)}</h4>
            <p class="dh-risk"><span class="dh-risk-lbl">Risk</span> ${annotateTickers(pick.key_risk || "")}</p>
            <div class="dh-detail">
                <p class="dh-why"><span class="dh-detail-lbl">Why now</span> ${annotateTickers(pick.why_now || "")}</p>
                <p class="dh-watch"><span class="dh-detail-lbl">Check before acting</span> ${annotateTickers(pick.what_would_change_it || "")}</p>
            </div>
            <div class="dh-actions">
                <button class="dh-recheck" data-action="recheck_highlight"
                        data-identifier="${escapeHtml(pick.identifier)}"
                        data-strategy="${escapeHtml(pick.strategy_key)}"
                        data-ticker="${escapeHtml(tickerOfPick(pick))}">Check this now</button>
                <button class="dh-toggle" data-action="toggle_pick_detail">Why this</button>
            </div>
            <div class="dh-result"></div>
        </article>
    `;
}


/**
 * Work out which ticker a pick belongs to.
 * A stock pick is its own ticker; an option contract carries it as the leading letters of the OCC symbol.
 */
function tickerOfPick(pick) {
    if (pick.strategy_key === "equity") {
        return pick.identifier;
    }

    const match = String(pick.identifier).match(/^([A-Z.]+)\d{6}[CP]\d{8}$/);
    return match ? match[1] : pick.identifier;
}

/** Format a stored UTC timestamp in the reader's own timezone. */
function localTimeOf(timestamp) {
    try {
        return new Date(timestamp).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
    } catch (error) {
        return "";
    }
}

/**
 * Re-scan the ticker behind one pick and report what it offers at current prices.
 * Only a candidate that still passes today's rules becomes placeable, and it is placed
 * against the fresh scan the re-check just saved rather than the hours-old one.
 */
async function recheckHighlight(clickedButton) {
    const card = clickedButton.closest(".dh-pick");
    const result = card.querySelector(".dh-result");
    const originalText = clickedButton.textContent;

    clickedButton.disabled = true;
    clickedButton.textContent = "Checking...";
    result.innerHTML = `<p class="dh-checking">Re-scanning ${escapeHtml(clickedButton.dataset.ticker)} at current prices...</p>`;

    try {
        const response = await apiFetch("/api/recommendations/highlights/recheck", {
            auth: true,
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                strategy_key: clickedButton.dataset.strategy,
                identifier: clickedButton.dataset.identifier,
                ticker_symbol: clickedButton.dataset.ticker,
            }),
        });

        if (!response.ok) {
            throw new Error(await brokerErrorMessage(response, `Re-check failed (status ${response.status}).`));
        }

        renderRecheckResult(result, await response.json());
    } catch (error) {
        result.innerHTML = `<p class="dh-stale">${escapeHtml(error.message)}</p>`;
    } finally {
        clickedButton.disabled = false;
        clickedButton.textContent = originalText;
    }
}

/** Show the re-checked numbers, and a place button only when the pick still qualifies. */
function renderRecheckResult(container, data) {
    const view = strategyView(data.strategy_key);
    const candidate = data.candidate;

    if (!candidate) {
        container.innerHTML = `
            <p class="dh-stale">${escapeHtml(data.reason)}</p>
            ${(data.alternatives || []).length ? `<p class="dh-alt-note">${(data.alternatives || []).length} other candidate(s) on this ticker still qualify. Run a scan to review them.</p>` : ""}
        `;
        return;
    }

    // The re-check saved its own run, so placing this uses a scan the freshness rule accepts.
    container.innerHTML = `
        <div class="dh-fresh">
            <p class="dh-fresh-head">${escapeHtml(data.reason)}</p>
            <div class="dh-fresh-stats">
                ${view.heroStats(candidate).map(renderDetailStat).join("")}
            </div>
            ${view.canPlace ? `
                <button data-action="place_highlight"
                        data-run="${escapeHtml(data.recommendation_run_id)}"
                        data-contract="${escapeHtml(candidate[view.idOf ? "contractSymbol" : "tickerSymbol"] || "")}">Paper place</button>
            ` : `<p class="dh-advisory">${escapeHtml(view.advisoryNote || "")}</p>`}
        </div>
    `;
}

/**
 * Place a re-checked pick against the fresh run the re-check created.
 * This is the same decision endpoint the manual cards use, so every placement check still applies.
 */
async function placeHighlight(clickedButton) {
    const runId = clickedButton.dataset.run;
    const contractSymbol = clickedButton.dataset.contract;
    const originalText = clickedButton.textContent;

    clickedButton.disabled = true;
    clickedButton.textContent = "Placing...";

    const previousRunId = currentRecommendationRunId;
    currentRecommendationRunId = runId;
    const result = await submitDecision("place_paper_order", contractSymbol);
    currentRecommendationRunId = previousRunId;

    if (result?.order_submitted) {
        showToast("Paper order placed", `${contractSymbol} submitted to Alpaca (${result.alpaca_order?.status || "submitted"}).`);
        clickedButton.textContent = "Placed";
        renderRecsMetrics(result);
        return;
    }

    showToast("Paper order failed", result?.order_error || "Alpaca did not accept the order.", "error");
    clickedButton.disabled = false;
    clickedButton.textContent = originalText;
}
