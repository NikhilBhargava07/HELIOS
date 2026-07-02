/** Load recommendation, trend, news, market-take, and portfolio API data. */

async function loadRecommendations() {
    if (button) {
        button.disabled = true;
    }
    recommendationStatus.textContent = "Scanning approved tickers and asking the agent...";

    try {
        const response = await apiFetch("/api/recommendations");

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
        if (button) {
            button.disabled = false;
        }
    }
}

async function loadTrends() {
    trendsButton.disabled = true;
    trendStatus.textContent = "Loading market trends...";

    try {
        const response = await apiFetch("/api/market/trends");

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
        const response = await apiFetch("/api/market/news");

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
    marketTakeStatus.textContent = "Starting AI market take job...";

    try {
        const response = await apiFetch("/api/market/take/jobs", {
            method: "POST",
        });

        if (!response.ok) {
            throw new Error(`Request failed with status ${response.status}`);
        }

        const job = await response.json();
        marketTakeStatus.textContent = "AI job started. Waiting for result...";
        await pollMarketTakeJob(job.job_id);
    } catch (error) {
        marketTakeStatus.textContent = `Error: ${error.message}`;
        summarizeMarketButton.disabled = false;
    }
}

async function pollMarketTakeJob(jobId, attempt = 1) {
    const maxAttempts = 36;
    const pollDelayMs = 2500;

    try {
        const response = await apiFetch(`/api/market/take/jobs/${jobId}`);

        if (!response.ok) {
            throw new Error(`Request failed with status ${response.status}`);
        }

        const job = await response.json();

        if (job.status === "complete") {
            const result = job.result || {};
            companyNames = result.company_names || companyNames;
            renderMarketTake(result);
            marketTakeStatus.textContent = "AI market take loaded.";
            summarizeMarketButton.disabled = false;
            return;
        }

        if (job.status === "failed") {
            throw new Error(job.error?.message || "AI market take job failed.");
        }

        if (attempt >= maxAttempts) {
            throw new Error("AI market take is still running. Try again in a moment.");
        }

        marketTakeStatus.textContent = `AI job ${job.status}. Checking again...`;
        setTimeout(() => pollMarketTakeJob(jobId, attempt + 1), pollDelayMs);
    } catch (error) {
        marketTakeStatus.textContent = `Error: ${error.message}`;
        summarizeMarketButton.disabled = false;
    }
}

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
        const response = await apiFetch("/api/dashboard");

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

/**
 * Begin periodic dashboard refreshes while the Capital tab is visible.
 * This keeps order status and position data close to Alpaca without requiring the user to manually reload.
 */
function startDashboardRefresh() {
    stopDashboardRefresh();
    dashboardRefreshIntervalId = setInterval(
        () => loadDashboard(false),
        DASHBOARD_REFRESH_MS,
    );
}

/**
 * Stop background dashboard refreshes when the user leaves the Capital tab.
 * Hidden pages should not keep polling the backend and broker account.
 */
function stopDashboardRefresh() {
    if (dashboardRefreshIntervalId) {
        clearInterval(dashboardRefreshIntervalId);
        dashboardRefreshIntervalId = null;
    }
}
