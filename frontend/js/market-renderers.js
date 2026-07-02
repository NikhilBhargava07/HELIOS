/** Render trend, news, and portfolio-aware AI market panels. */

/**
 * Render recent price movement cards for approved tickers.
 * The first view stays short for readability, while the stored full list supports the See More toggle.
 */
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

/**
 * Merge latest-price refresh data into the existing trend objects.
 * This preserves already loaded historical changes while updating only the live price pill.
 */
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
        const response = await apiFetch("/api/market/prices");

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

/**
 * Start the latest-price polling timer for the Trends page.
 * Restarting clears any old timer so repeated loads do not create duplicate refresh loops.
 */
function startPriceRefresh() {
    if (priceRefreshIntervalId) {
        clearInterval(priceRefreshIntervalId);
    }

    priceRefreshIntervalId = setInterval(refreshLatestPrices, PRICE_REFRESH_MS);
}

/**
 * Rotate trend cards between percent change and dollar change.
 * This gives users both views without doubling the amount of visible text in each card.
 */
function startTrendMetricRotation() {
    if (trendMetricRotateIntervalId) {
        clearInterval(trendMetricRotateIntervalId);
    }

    trendList.classList.remove("show-dollar");
    trendMetricRotateIntervalId = setInterval(() => {
        trendList.classList.toggle("show-dollar");
    }, TREND_METRIC_ROTATE_MS);
}

/**
 * Stop the latest-price polling timer when trends are not visible.
 * This keeps hidden tabs from making unnecessary market-data requests.
 */
function stopPriceRefresh() {
    if (priceRefreshIntervalId) {
        clearInterval(priceRefreshIntervalId);
    }

    priceRefreshIntervalId = null;
}

/**
 * Stop the percent/dollar rotation animation and reset cards to percent view.
 * Resetting the class keeps the next visit predictable for the user.
 */
function stopTrendMetricRotation() {
    if (trendMetricRotateIntervalId) {
        clearInterval(trendMetricRotateIntervalId);
    }

    trendMetricRotateIntervalId = null;
    trendList.classList.remove("show-dollar");
}

/**
 * Render curated external news articles with source, date, ticker chips, and relevance notes.
 * The UI shows a compact initial set so the News tab stays readable before the user expands it.
 */
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
            <div class="news-meta-row">
                <span class="news-source">${escapeHtml(item.source || "Unknown source")}</span>
                <span>${escapeHtml(newsDateText(item.created_at))}</span>
                <span>${escapeHtml(String(item.source_quality || "unrated").replaceAll("_", " "))}</span>
            </div>
            <a href="${escapeHtml(safeExternalUrl(item.url))}" target="_blank" rel="noopener noreferrer">${escapeHtml(item.headline)}</a>
            <div class="news-chip-row">
                ${(item.symbols || []).slice(0, 5).map(symbol => `
                    <span class="news-chip">${tickerTooltip(symbol)}</span>
                `).join("")}
                ${(item.tags || []).slice(0, 5).map(tag => `
                    <span class="news-chip muted">${escapeHtml(String(tag).replaceAll("_", " "))}</span>
                `).join("")}
            </div>
            <p>${escapeHtml(item.why_it_matters || item.summary || "")}</p>
        </article>
    `).join("");

    toggleNewsButton.classList.toggle("hidden", news.length <= DEFAULT_NEWS_COUNT);
    toggleNewsButton.textContent = showAllNews ? "Show fewer news items" : "See more news";
}

/**
 * Render the AI Market Take response into structured reasoning cards.
 * The layout separates the detailed thesis, mood, CSP stance, actions, open positions, and latest recommendations so the user can scan quickly.
 */
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
            <article class="take-card take-card-csp-angle">
                <span class="take-label">CSP angle</span>
                <p>${escapeHtml(take.csp_take || "Keep using the hard filters.")}</p>
            </article>
            <article class="take-card take-card-action">
                <span class="take-label">Do this</span>
                <p>${escapeHtml(take.action || "Prioritize clean candidates.")}</p>
            </article>
            <article class="take-card take-card-avoid warning-card">
                <span class="take-label">Avoid this</span>
                <p>${escapeHtml(take.avoid || "Do not force trades for premium.")}</p>
            </article>
            <article class="take-card take-card-wide">
                <span class="take-label">Your open CSPs</span>
                <p>${annotateTickers(take.portfolio_take || "No current positions were available to review.")}</p>
            </article>
            <article class="take-card take-card-wide">
                <span class="take-label">Latest recommendations</span>
                <p>${annotateTickers(take.recommendation_take || "No recent recommendation run was available to compare.")}</p>
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
