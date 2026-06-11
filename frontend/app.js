const button = document.querySelector("#load-recommendations");
const trendsButton = document.querySelector("#load-trends");
const newsButton = document.querySelector("#load-news");
const summarizeMarketButton = document.querySelector("#summarize-market");
const menuToggle = document.querySelector("#menu-toggle");
const sidebar = document.querySelector("#sidebar");
const navLinks = document.querySelectorAll(".nav-link");
const panels = document.querySelectorAll(".tab-panel");
const recommendationStatus = document.querySelector("#recommendation-status");
const trendStatus = document.querySelector("#trend-status");
const newsStatus = document.querySelector("#news-status");
const marketTakeStatus = document.querySelector("#market-take-status");
const reviewEl = document.querySelector("#agent-review");
const candidateList = document.querySelector("#candidate-list");
const dashboardEl = document.querySelector("#dashboard");
const trendList = document.querySelector("#trend-list");
const newsList = document.querySelector("#news-list");
const marketTakeEl = document.querySelector("#market-take-output");
const toggleTrendsButton = document.querySelector("#toggle-trends");
const toggleNewsButton = document.querySelector("#toggle-news");

let currentRecommendationRunId = null;
let latestTrends = [];
let latestNews = [];
let showAllTrends = false;
let showAllNews = false;
const DEFAULT_TREND_COUNT = 6;
const DEFAULT_NEWS_COUNT = 5;

function money(value) {
    return `$${Number(value).toLocaleString(undefined, {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
    })}`;
}

function percent(value) {
    if (value === null || value === undefined) {
        return "n/a";
    }

    return `${Number(value).toFixed(2)}%`;
}

function signedPercent(value) {
    if (value === null || value === undefined) {
        return "n/a";
    }

    const number = Number(value);
    const sign = number > 0 ? "+" : "";

    return `${sign}${number.toFixed(2)}%`;
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

function renderTrends(trends) {
    latestTrends = trends;

    if (!trends.length) {
        trendList.innerHTML = "<p>No trend data available.</p>";
        return;
    }

    const visibleTrends = showAllTrends ? trends : trends.slice(0, DEFAULT_TREND_COUNT);

    trendList.classList.remove("empty");
    trendList.innerHTML = visibleTrends.map(trend => `
        <article class="trend-card">
            <h3>${trend.ticker}</h3>
            <div><span class="label">1D:</span> ${signedPercent(trend["1d"])}</div>
            <div><span class="label">5D:</span> ${signedPercent(trend["5d"])}</div>
            <div><span class="label">2W:</span> ${signedPercent(trend["2w"])}</div>
            <div><span class="label">1M:</span> ${signedPercent(trend["1m"])}</div>
            <div><span class="label">YTD:</span> ${signedPercent(trend.ytd)}</div>
        </article>
    `).join("");

    toggleTrendsButton.classList.toggle("hidden", trends.length <= DEFAULT_TREND_COUNT);
    toggleTrendsButton.textContent = showAllTrends ? "Show fewer trends" : "See more trends";
}

function renderNews(news) {
    latestNews = news;

    if (!news.length) {
        newsList.innerHTML = "<p>No recent news returned.</p>";
        return;
    }

    const visibleNews = showAllNews ? news : news.slice(0, DEFAULT_NEWS_COUNT);

    newsList.classList.remove("empty");
    newsList.innerHTML = visibleNews.map(item => `
        <article class="news-item">
            <a href="${item.url}" target="_blank" rel="noopener noreferrer">${item.headline}</a>
            <div class="label">${item.source || "Unknown source"} · ${(item.symbols || []).join(", ")}</div>
            <p>${item.summary || ""}</p>
        </article>
    `).join("");

    toggleNewsButton.classList.toggle("hidden", news.length <= DEFAULT_NEWS_COUNT);
    toggleNewsButton.textContent = showAllNews ? "Show fewer news items" : "See more news";
}

function renderMarketTake(take) {
    marketTakeEl.classList.remove("empty");
    marketTakeEl.innerHTML = `
        <div>${take.summary}</div>
        <div><span class="label">CSP take:</span> ${take.csp_take}</div>
        <ul>
            ${(take.scenarios || []).map(scenario => `<li>${scenario}</li>`).join("")}
        </ul>
    `;
}

async function loadRecommendations() {
    button.disabled = true;
    recommendationStatus.textContent = "Scanning approved tickers and asking the agent...";

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
        recommendationStatus.textContent = `Scanned ${data.approved_tickers.length} approved tickers.`;
    } catch (error) {
        recommendationStatus.textContent = `Error: ${error.message}`;
    } finally {
        button.disabled = false;
    }
}

async function loadTrends() {
    trendsButton.disabled = true;
    trendStatus.textContent = "Loading market trends...";

    try {
        const response = await fetch("/api/market/trends");

        if (!response.ok) {
            throw new Error(`Request failed with status ${response.status}`);
        }

        const data = await response.json();
        renderTrends(data.trends || []);
        trendStatus.textContent = `Loaded ${(data.trends || []).length} trend records.`;
    } catch (error) {
        trendStatus.textContent = `Error: ${error.message}`;
    } finally {
        trendsButton.disabled = false;
    }
}

async function loadNews() {
    newsButton.disabled = true;
    newsStatus.textContent = "Loading recent news...";

    try {
        const response = await fetch("/api/market/news");

        if (!response.ok) {
            throw new Error(`Request failed with status ${response.status}`);
        }

        const data = await response.json();
        renderNews(data.news || []);
        newsStatus.textContent = `Loaded ${(data.news || []).length} recent headlines.`;
    } catch (error) {
        newsStatus.textContent = `Error: ${error.message}`;
    } finally {
        newsButton.disabled = false;
    }
}

async function loadMarketTake() {
    summarizeMarketButton.disabled = true;
    marketTakeStatus.textContent = "Asking AI for market take...";

    try {
        const response = await fetch("/api/market/take", {
            method: "POST",
        });

        if (!response.ok) {
            throw new Error(`Request failed with status ${response.status}`);
        }

        const data = await response.json();
        renderMarketTake(data);
        marketTakeStatus.textContent = "AI market take loaded.";
    } catch (error) {
        marketTakeStatus.textContent = `Error: ${error.message}`;
    } finally {
        summarizeMarketButton.disabled = false;
    }
}

async function submitDecision(action, contractSymbol) {
    if (!currentRecommendationRunId) {
        recommendationStatus.textContent = "Run recommendations before recording a decision.";
        return;
    }

    recommendationStatus.textContent = "Recording decision...";

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
        recommendationStatus.textContent = action === "place_paper_order"
            ? "Paper order recorded."
            : "Recommendation discarded.";
    } catch (error) {
        recommendationStatus.textContent = `Error: ${error.message}`;
    }
}

function showTab(tabName) {
    panels.forEach(panel => {
        panel.classList.toggle("active", panel.dataset.panel === tabName);
    });

    navLinks.forEach(link => {
        link.classList.toggle("active", link.dataset.tab === tabName);
    });

    sidebar.classList.remove("open");
}

window.showTab = showTab;

button.addEventListener("click", loadRecommendations);
trendsButton.addEventListener("click", loadTrends);
newsButton.addEventListener("click", loadNews);
summarizeMarketButton.addEventListener("click", loadMarketTake);
menuToggle.addEventListener("click", () => sidebar.classList.toggle("open"));

sidebar.addEventListener("click", (event) => {
    const clickedLink = event.target.closest(".nav-link");

    if (!clickedLink) {
        return;
    }

    showTab(clickedLink.dataset.tab);
});

toggleTrendsButton.addEventListener("click", () => {
    showAllTrends = !showAllTrends;
    renderTrends(latestTrends);
});

toggleNewsButton.addEventListener("click", () => {
    showAllNews = !showAllNews;
    renderNews(latestNews);
});

candidateList.addEventListener("click", (event) => {
    const clickedButton = event.target.closest("button[data-action]");

    if (!clickedButton) {
        return;
    }

    submitDecision(clickedButton.dataset.action, clickedButton.dataset.contract);
});
