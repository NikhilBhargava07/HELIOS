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
const toastEl = document.querySelector("#toast");

let currentRecommendationRunId = null;
let companyNames = {};
let candidatePool = [];
let visibleCandidates = [];
let queuedCandidates = [];
let visibleCandidateLimit = 3;
let latestTrends = [];
let latestNews = [];
let showAllTrends = false;
let showAllNews = false;
let priceRefreshIntervalId = null;
let trendMetricRotateIntervalId = null;
const DEFAULT_TREND_COUNT = 6;
const DEFAULT_NEWS_COUNT = 5;
const PRICE_REFRESH_MS = 15000;
const TREND_METRIC_ROTATE_MS = 5000;
const NEUTRAL_TREND_PERCENT_THRESHOLD = 0.2;
const TOAST_TIMEOUT_MS = 5200;
const GLOSSARY = {
    "assignment risk": "The chance you must buy 100 shares at the strike price if the put is assigned.",
    "cash-secured put": "A put option you sell while keeping enough cash to buy 100 shares if assigned.",
    delta: "A rough estimate of how much the option price moves when the stock moves $1. Lower delta usually means farther from the current stock price.",
    IV: "Implied volatility. Higher IV can mean richer premium, but also more uncertainty.",
    "implied volatility": "The market's estimate of how much the stock may move. Higher usually means higher option prices.",
    spread: "The gap between bid and ask. Tighter spreads usually mean easier entry and exit.",
    premium: "Money received for selling the put contract.",
    "margin of safety": "Extra room between the current stock price and your strike or breakeven price.",
    "support": "A price area where buyers have recently stepped in.",
    "rates": "Interest rates. Higher rates can pressure growth stocks because future earnings become less attractive.",
    inflation: "Rising prices across the economy. It can affect Fed decisions and stock valuations.",
    "Fed": "The Federal Reserve, the U.S. central bank that influences interest rates.",
    "relief rally": "A short bounce after selling pressure, not always a true trend change.",
    "liquid": "Easy to trade because there are enough buyers and sellers.",
    "volatility": "How much and how quickly a stock price moves.",
};

function money(value) {
    return `$${Number(value).toLocaleString(undefined, {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
    })}`;
}

function candidateByContract(contractSymbol) {
    return candidatePool.find(candidate => candidate.contractSymbol === contractSymbol);
}

function candidateIsAffordable(candidate, availableCash) {
    if (availableCash === null || availableCash === undefined) {
        return true;
    }

    return Number(candidate.cashRequired || 0) <= Number(availableCash);
}

function filterAffordableCandidates(candidates, availableCash) {
    return (candidates || []).filter(candidate => candidateIsAffordable(candidate, availableCash));
}

function selectedContractIsAffordable(review, candidates) {
    if (!review?.selected_contract) {
        return false;
    }

    return candidates.some(candidate => candidate.contractSymbol === review.selected_contract);
}

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

function signedMoney(value) {
    if (value === null || value === undefined) {
        return "n/a";
    }

    const number = Number(value);
    const sign = number > 0 ? "+" : number < 0 ? "-" : "";

    return `${sign}${money(Math.abs(number))}`;
}

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

function priceText(value) {
    if (value === null || value === undefined) {
        return "Price n/a";
    }

    return money(value);
}

function companyNameForTicker(ticker) {
    return companyNames[ticker] || ticker;
}

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

function formatDecision(value) {
    return String(value || "")
        .replaceAll("_", " ")
        .replace(/\b\w/g, letter => letter.toUpperCase());
}

function escapeHtml(value) {
    return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
}

function glossaryTerm(term) {
    return `
        <span class="tooltip-term" tabindex="0">
            ${escapeHtml(term)}
            <span class="tooltip-bubble">${escapeHtml(GLOSSARY[term])}</span>
        </span>
    `;
}

function renderGlossaryChips(terms) {
    return terms.map(term => `
        <span class="glossary-chip">
            ${glossaryTerm(term)}
        </span>
    `).join("");
}

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

function marketMoodExplanation(mood) {
    const explanations = {
        Calm: "Prices are moving more steadily, so fewer warning signs are showing up.",
        Mixed: "Some stocks look strong while others look weak, so stock selection matters.",
        Choppy: "Prices are bouncing around, so a good-looking premium can come with extra risk.",
        Risky: "The market setup looks unstable, so passing on trades may be reasonable.",
    };

    return explanations[mood] || "This describes the overall feel of the current market setup.";
}

function cspStanceExplanation(stance) {
    const explanations = {
        Favorable: "The setup looks reasonable for filtered CSP ideas, while still using position rules.",
        Selective: "Only the cleanest CSP candidates deserve attention right now.",
        Cautious: "Premium may look tempting, but risk deserves extra weight.",
        Wait: "The setup does not look clear enough to force CSP trades.",
    };

    return explanations[stance] || "This describes how aggressive the CSP search should be.";
}

function annotateTickers(text) {
    const escaped = escapeHtml(text || "");
    const tickers = Object.keys(companyNames).sort((a, b) => b.length - a.length);

    if (!tickers.length) {
        return escaped;
    }

    const tickerPattern = new RegExp(`\\b(${tickers.join("|")})(?=\\b|\\d)`, "g");

    return escaped.replace(tickerPattern, match => tickerTooltip(match));
}

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

function renderCandidates(candidates) {
    candidatePool = candidates;
    visibleCandidates = candidatePool.slice(0, visibleCandidateLimit);
    queuedCandidates = candidatePool.slice(visibleCandidateLimit);
    renderVisibleCandidates();
}

function renderVisibleCandidates() {
    if (!visibleCandidates.length) {
        candidateList.innerHTML = "<p>No candidates passed the filters.</p>";
        return;
    }

    candidateList.innerHTML = visibleCandidates.map(candidate => `
        <article class="candidate-card" data-contract="${candidate.contractSymbol}">
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

function renderDashboard(dashboard) {
    if (!dashboard) {
        return;
    }

    const capital = dashboard.capital || dashboard;
    const positions = dashboard.open_positions || capital.open_positions || [];
    const orders = dashboard.paper_orders || [];

    dashboardEl.classList.remove("empty");
    dashboardEl.innerHTML = `
        <p class="ledger-note">
            This is a Postgres paper ledger saved by the prototype. Alpaca may still reject orders if paper buying power changes.
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
                ${tickerTooltip(position.ticker_symbol)} ${money(position.strike)} CSP ·
                Cash ${money(position.cash_required)} ·
                Premium ${money(position.premium_received)}
            </div>
        `).join("") : "<p>No open paper positions.</p>"}
        <h3>Recent Paper Orders</h3>
        ${orders.length ? orders.slice().reverse().map(order => `
            <div class="history-row">
                ${order.status}: ${tickerTooltip(order.ticker_symbol)} ${money(order.strike)} CSP ·
                Premium ${money(order.premium_received)}
            </div>
        `).join("") : "<p>No paper orders yet.</p>"}
    `;
}

function renderTrends(trends) {
    latestTrends = trends;

    if (!trends.length) {
        trendList.innerHTML = "<p>No trend data available.</p>";
        stopTrendMetricRotation();
        return;
    }

    const visibleTrends = showAllTrends ? trends : trends.slice(0, DEFAULT_TREND_COUNT);

    trendList.classList.remove("empty");
    trendList.innerHTML = visibleTrends.map(trend => `
        <article class="trend-card">
            <div class="trend-card-header">
                <div>
                    <h3>${tickerTooltip(trend.ticker)}</h3>
                </div>
                <span class="price-pill" data-price-symbol="${trend.ticker}">
                    ${priceText(trend.current_price)}
                </span>
            </div>
            ${trendMetric("1D", trend["1d"], trend["1d_dollar"])}
            ${trendMetric("5D", trend["5d"], trend["5d_dollar"])}
            ${trendMetric("2W", trend["2w"], trend["2w_dollar"])}
            ${trendMetric("1M", trend["1m"], trend["1m_dollar"])}
            ${trendMetric("YTD", trend.ytd, trend.ytd_dollar)}
        </article>
    `).join("");

    toggleTrendsButton.classList.toggle("hidden", trends.length <= DEFAULT_TREND_COUNT);
    toggleTrendsButton.textContent = showAllTrends ? "Show fewer trends" : "See more trends";
}

function mergeLatestPrices(prices) {
    latestTrends = latestTrends.map(trend => {
        const latest = prices[trend.ticker];

        if (!latest) {
            return trend;
        }

        return {
            ...trend,
            current_price: latest.price,
            price_timestamp: latest.timestamp,
        };
    });
}

async function refreshLatestPrices() {
    if (!latestTrends.length) {
        return;
    }

    try {
        const response = await fetch("/api/market/prices");

        if (!response.ok) {
            throw new Error(`Request failed with status ${response.status}`);
        }

        const data = await response.json();
        mergeLatestPrices(data.prices || {});
        renderTrends(latestTrends);
        trendStatus.textContent = `Prices refreshed ${new Date().toLocaleTimeString([], {
            hour: "numeric",
            minute: "2-digit",
            second: "2-digit",
        })}.`;
    } catch (error) {
        trendStatus.textContent = `Price refresh failed: ${error.message}`;
    }
}

function startPriceRefresh() {
    if (priceRefreshIntervalId) {
        clearInterval(priceRefreshIntervalId);
    }

    priceRefreshIntervalId = setInterval(refreshLatestPrices, PRICE_REFRESH_MS);
}

function startTrendMetricRotation() {
    if (trendMetricRotateIntervalId) {
        clearInterval(trendMetricRotateIntervalId);
    }

    trendList.classList.remove("show-dollar");
    trendMetricRotateIntervalId = setInterval(() => {
        trendList.classList.toggle("show-dollar");
    }, TREND_METRIC_ROTATE_MS);
}

function stopTrendMetricRotation() {
    if (trendMetricRotateIntervalId) {
        clearInterval(trendMetricRotateIntervalId);
    }

    trendMetricRotateIntervalId = null;
    trendList.classList.remove("show-dollar");
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
    const scenarios = take.scenarios || [];
    const companyNotes = take.company_notes || [];
    const glossaryTerms = getRelevantGlossaryTerms(take);

    marketTakeEl.classList.remove("empty");
    marketTakeEl.innerHTML = `
        <div class="take-grid">
            <article class="take-card take-card-primary take-card-wide">
                <span class="take-label">Reasoned take</span>
                <h3>${escapeHtml(take.headline || "Market risk check")}</h3>
                <p>${escapeHtml(take.reasoned_take || take.summary || "Use this as context, not a prediction.")}</p>
            </article>
            <div class="take-card-stack">
                <article class="take-card take-card-compact">
                    <span class="take-label">Market mood</span>
                    <strong>${escapeHtml(take.market_mood || "Mixed")}</strong>
                    <p class="take-explainer">${escapeHtml(marketMoodExplanation(take.market_mood || "Mixed"))}</p>
                </article>
                <article class="take-card take-card-compact">
                    <span class="take-label">CSP stance</span>
                    <strong>${escapeHtml(take.csp_stance || "Selective")}</strong>
                    <p class="take-explainer">${escapeHtml(cspStanceExplanation(take.csp_stance || "Selective"))}</p>
                </article>
            </div>
            <article class="take-card">
                <span class="take-label">CSP angle</span>
                <p>${escapeHtml(take.csp_take || "Keep using the hard filters.")}</p>
            </article>
            <article class="take-card">
                <span class="take-label">Do this</span>
                <p>${escapeHtml(take.action || "Prioritize clean candidates.")}</p>
            </article>
            <article class="take-card warning-card">
                <span class="take-label">Avoid this</span>
                <p>${escapeHtml(take.avoid || "Do not force trades for premium.")}</p>
            </article>
        </div>
        ${companyNotes.length ? `
            <h3 class="mini-heading">Companies to watch</h3>
            <div class="company-note-grid">
                ${companyNotes.map(note => `
                    <article class="company-note">
                        <strong>${tickerTooltip(note.ticker || "Ticker")}</strong>
                        <p>${escapeHtml(note.note || "")}</p>
                    </article>
                `).join("")}
            </div>
        ` : ""}
        <h3 class="mini-heading">Next few weeks</h3>
        <ul class="scenario-list">
            ${scenarios.map(scenario => `<li>${escapeHtml(scenario)}</li>`).join("")}
        </ul>
        <div class="glossary-row">
            <span class="label">Hover terms:</span>
            ${renderGlossaryChips(glossaryTerms)}
        </div>
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
        const effectiveAvailableCash = data.capital?.effective_available_csp_capital;
        const affordableCandidates = filterAffordableCandidates(data.candidates || [], effectiveAvailableCash);
        const affordableReview = reviewWithAffordableSelection(
            data.review,
            affordableCandidates,
            effectiveAvailableCash,
        );

        currentRecommendationRunId = data.recommendation_run_id;
        companyNames = data.company_names || companyNames;
        renderCandidates(affordableCandidates);
        renderReview(affordableReview);
        renderDashboard(data.dashboard);
        recommendationStatus.textContent = `Scanned ${data.approved_tickers.length} approved tickers. Showing ${affordableCandidates.length} cash-backed candidates.`;
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
        const trends = data.trends || [];
        companyNames = data.company_names || companyNames;
        renderTrends(trends);
        trendStatus.textContent = `Loaded ${trends.length} trend records. Prices refresh every ${PRICE_REFRESH_MS / 1000}s.`;
        startPriceRefresh();

        if (trends.length) {
            startTrendMetricRotation();
        }
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
        newsStatus.textContent = `Loaded ${(data.news || []).length} headlines from the last ${data.lookback_days || 30} days.`;
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
        companyNames = data.company_names || companyNames;
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
        return false;
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

        if (action === "place_paper_order") {
            if (data.order_submitted) {
                recommendationStatus.textContent = `Alpaca paper order submitted (${data.alpaca_order?.status || "submitted"}).`;
            } else {
                recommendationStatus.textContent = `Alpaca paper order failed: ${data.order_error || "unknown error"}`;
            }
        } else {
            recommendationStatus.textContent = "Recommendation discarded.";
        }

        return data;
    } catch (error) {
        recommendationStatus.textContent = `Error: ${error.message}`;
        return null;
    }
}

function removeCandidateFromPool(contractSymbol) {
    const visibleIndex = visibleCandidates.findIndex(candidate => candidate.contractSymbol === contractSymbol);
    candidatePool = candidatePool.filter(candidate => candidate.contractSymbol !== contractSymbol);

    if (visibleIndex === -1) {
        renderCandidates(candidatePool);
        return;
    }

    const replacement = queuedCandidates.shift();

    if (replacement) {
        visibleCandidates[visibleIndex] = replacement;
    } else {
        visibleCandidates.splice(visibleIndex, 1);
    }

    renderVisibleCandidates();
}

async function discardCandidate(clickedButton) {
    const contractSymbol = clickedButton.dataset.contract;
    const card = clickedButton.closest(".candidate-card");
    const recorded = await submitDecision("discard", contractSymbol);

    if (!recorded) {
        return;
    }

    if (card) {
        card.classList.add("discarding");
        setTimeout(() => removeCandidateFromPool(contractSymbol), 180);
    } else {
        removeCandidateFromPool(contractSymbol);
    }
}

async function placeCandidate(clickedButton) {
    const contractSymbol = clickedButton.dataset.contract;
    const card = clickedButton.closest(".candidate-card");
    const candidate = candidateByContract(contractSymbol);
    const originalButtonText = clickedButton.textContent;

    clickedButton.disabled = true;
    clickedButton.textContent = "Placing...";

    const result = await submitDecision("place_paper_order", contractSymbol);

    if (!result) {
        clickedButton.disabled = false;
        clickedButton.textContent = originalButtonText;
        return;
    }

    if (!result.order_submitted) {
        showToast(
            "Paper order failed",
            result.order_error || "Alpaca did not accept the order.",
            "error",
        );
        clickedButton.disabled = false;
        clickedButton.textContent = originalButtonText;

        if (result.refresh_recommendations) {
            recommendationStatus.textContent = "Refreshing recommendations with current buying power...";
            loadRecommendations();
        }

        return;
    }

    showToast(
        "Paper order placed",
        `${candidate?.tickerSymbol || contractSymbol} ${money(candidate?.strike || 0)} put submitted to Alpaca (${result.alpaca_order?.status || "submitted"}).`,
    );

    if (card) {
        card.classList.add("discarding");
        setTimeout(() => removeCandidateFromPool(contractSymbol), 180);
    } else {
        removeCandidateFromPool(contractSymbol);
    }

    recommendationStatus.textContent = "Refreshing recommendations with updated buying power...";
    loadRecommendations();
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

    if (clickedButton.dataset.action === "discard") {
        discardCandidate(clickedButton);
        return;
    }

    if (clickedButton.dataset.action === "place_paper_order") {
        placeCandidate(clickedButton);
    }
});

reviewEl.addEventListener("click", (event) => {
    const clickedButton = event.target.closest("button[data-action]");

    if (!clickedButton) {
        return;
    }

    if (clickedButton.dataset.action === "place_paper_order") {
        placeCandidate(clickedButton);
    }
});
