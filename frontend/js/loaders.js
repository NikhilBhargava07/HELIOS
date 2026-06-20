/** Load recommendation, trend, news, market-take, and portfolio API data. */

/** Request a new recommendation run and update all related panels. */
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

/** Load historical trends, current prices, and refresh timers. */
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

/** Load recent external market news. */
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

/** Request an AI take using live positions and the latest recommendations. */
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

/** Refresh live Alpaca positions whenever the Capital tab opens. */
async function loadDashboard(showLoading = true) {
    if (dashboardRequestInFlight) {
        return;
    }
    dashboardRequestInFlight = true;
    if (showLoading) {
        dashboardEl.classList.remove("empty");
        dashboardEl.textContent = "Loading current Alpaca positions and orders...";
    }

    try {
        const response = await fetch("/api/dashboard");

        if (!response.ok) {
            throw new Error(`Request failed with status ${response.status}`);
        }

        renderDashboard(await response.json());
    } catch (error) {
        dashboardEl.textContent = `Could not load positions: ${error.message}`;
    } finally {
        dashboardRequestInFlight = false;
    }
}

/** Poll Alpaca order and position state while the Capital tab is visible. */
function startDashboardRefresh() {
    stopDashboardRefresh();
    dashboardRefreshIntervalId = setInterval(
        () => loadDashboard(false),
        DASHBOARD_REFRESH_MS,
    );
}

/** Stop portfolio polling after the user leaves the Capital tab. */
function stopDashboardRefresh() {
    if (dashboardRefreshIntervalId) {
        clearInterval(dashboardRefreshIntervalId);
        dashboardRefreshIntervalId = null;
    }
}
