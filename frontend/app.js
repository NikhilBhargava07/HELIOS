const button = document.querySelector("#load-recommendations");
const statusText = document.querySelector("#status");
const reviewEl = document.querySelector("#agent-review");
const candidateList = document.querySelector("#candidate-list");
const dashboardEl = document.querySelector("#dashboard");

let currentRecommendationRunId = null;

function money(value) {
    return `$${Number(value).toLocaleString(undefined, {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
    })}`;
}

function percent(value) {
    return `${Number(value).toFixed(2)}%`;
}

function renderReview(review) {
    reviewEl.classList.remove("empty");
    reviewEl.innerHTML = `
        <div><span class="label">Decision:</span> ${review.decision}</div>
        <div><span class="label">Selected:</span> ${review.selected_contract || "None"}</div>
        <div><span class="label">Summary:</span> ${review.summary}</div>
        <div class="warning"><span class="label">Risk note:</span> ${review.risk_note}</div>
    `;
}

function renderCandidates(candidates) {
    if (!candidates.length) {
        candidateList.innerHTML = "<p>No candidates passed the filters.</p>";
        return;
    }

    candidateList.innerHTML = candidates.map((candidate, index) => `
        <article class="candidate-card">
            <h3>${index + 1}. Sell 1 ${candidate.tickerSymbol} ${money(candidate.strike)} put</h3>
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

function renderDashboard(dashboard) {
    if (!dashboard) {
        return;
    }

    const capital = dashboard.capital || dashboard;
    const positions = dashboard.open_positions || capital.open_positions || [];
    const orders = dashboard.paper_orders || [];

    dashboardEl.classList.remove("empty");
    dashboardEl.innerHTML = `
        <div class="dashboard-grid">
            <div><span class="label">Total capital:</span> ${money(capital.total_capital)}</div>
            <div><span class="label">Max CSP capital:</span> ${money(capital.max_csp_capital)}</div>
            <div><span class="label">Committed:</span> ${money(capital.committed_capital)}</div>
            <div><span class="label">Available CSP capital:</span> ${money(capital.available_csp_capital)}</div>
            <div><span class="label">Open positions:</span> ${capital.open_position_count}/${capital.max_open_positions}</div>
        </div>
        <h3>Open Positions</h3>
        ${positions.length ? positions.map(position => `
            <div class="history-row">
                ${position.ticker_symbol} ${money(position.strike)} CSP ·
                Cash ${money(position.cash_required)} ·
                Premium ${money(position.premium_received)}
            </div>
        `).join("") : "<p>No open paper positions.</p>"}
        <h3>Recent Paper Orders</h3>
        ${orders.length ? orders.slice().reverse().map(order => `
            <div class="history-row">
                ${order.status}: ${order.ticker_symbol} ${money(order.strike)} CSP ·
                Premium ${money(order.premium_received)}
            </div>
        `).join("") : "<p>No paper orders yet.</p>"}
    `;
}

async function loadRecommendations() {
    button.disabled = true;
    statusText.textContent = "Scanning approved tickers and asking the agent...";

    try {
        const response = await fetch("/api/recommendations");

        if (!response.ok) {
            throw new Error(`Request failed with status ${response.status}`);
        }

        const data = await response.json();

        currentRecommendationRunId = data.recommendation_run_id;
        renderReview(data.review);
        renderCandidates(data.candidates);
        renderDashboard(data.dashboard);
        statusText.textContent = `Scanned ${data.approved_tickers.length} approved tickers.`;
    } catch (error) {
        statusText.textContent = `Error: ${error.message}`;
    } finally {
        button.disabled = false;
    }
}

async function submitDecision(action, contractSymbol) {
    if (!currentRecommendationRunId) {
        statusText.textContent = "Run recommendations before recording a decision.";
        return;
    }

    statusText.textContent = "Recording decision...";

    try {
        const response = await fetch("/api/decisions", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
            },
            body: JSON.stringify({
                recommendation_run_id: currentRecommendationRunId,
                contract_symbol: contractSymbol,
                action,
            }),
        });

        if (!response.ok) {
            throw new Error(`Request failed with status ${response.status}`);
        }

        const data = await response.json();
        renderDashboard(data.dashboard);
        statusText.textContent = action === "place_paper_order"
            ? "Paper order recorded."
            : "Recommendation discarded.";
    } catch (error) {
        statusText.textContent = `Error: ${error.message}`;
    }
}

button.addEventListener("click", loadRecommendations);

candidateList.addEventListener("click", (event) => {
    const clickedButton = event.target.closest("button[data-action]");

    if (!clickedButton) {
        return;
    }

    submitDecision(clickedButton.dataset.action, clickedButton.dataset.contract);
});
