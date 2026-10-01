/** Render trend, news, and portfolio-aware AI market panels. */

/**
 * Render recent price movement cards for approved tickers.
 * The first view stays short for readability, while the stored full list supports the See More toggle.
 */
function renderTrends(trends) {
    latestTrends = trends;

    if (!trends.length) {
        trendList.innerHTML = "<p class=\"trend-empty\">No trend data available.</p>";
        toggleTrendsButton.classList.add("hidden");
        return;
    }

    let filtered = trends;
    if (trendFilter !== "All") {
        const allowed = new Set(TREND_CATEGORIES[trendFilter] || []);
        filtered = trends.filter(trend => allowed.has(trend.ticker));
    }

    if (trendSort === "move") {
        filtered = filtered.slice().sort((a, b) =>
            Math.abs(Number(b["1d"]) || 0) - Math.abs(Number(a["1d"]) || 0));
    }

    const visibleTrends = showAllTrends ? filtered : filtered.slice(0, DEFAULT_TREND_COUNT);

    trendList.classList.remove("empty");
    trendList.innerHTML = `
        <div class="trend-controls">
            <div class="trend-filters">
                ${["All", "ETFs", "Mega-tech", "Financials", "Consumer"].map(category => `
                    <button type="button" class="trend-pill ${category === trendFilter ? "active" : ""}" data-filter="${category}">${category}</button>
                `).join("")}
            </div>
            <button type="button" class="trend-sort ${trendSort === "move" ? "active" : ""}" data-sort-toggle>Biggest move</button>
        </div>
        ${visibleTrends.length ? `
            <div class="trend-grid-inner">
                ${visibleTrends.map(renderTrendTile).join("")}
            </div>
        ` : "<p class=\"trend-empty\">No tickers in this group.</p>"}
    `;

    toggleTrendsButton.classList.toggle("hidden", filtered.length <= DEFAULT_TREND_COUNT);
    toggleTrendsButton.textContent = showAllTrends ? "Show fewer" : `Show all ${filtered.length}`;
}

/**
 * Render one compact ticker tile: symbol, live price, 1-day move, and a reconstructed sparkline.
 * Clicking a tile expands it to reveal the full 1D/5D/2W/1M/YTD breakdown.
 */
/**
 * State how close a company's next report is, or say nothing at all.
 *
 * Funds never report, and a company whose date has not been fetched yet would be
 * misrepresented by a blank row, so both are simply left out. A report inside the
 * next week is marked, because that is when it starts changing a trade decision.
 */
function earningsLine(trend) {
    const days = trend.days_until_next_report;

    if (days === null || days === undefined) {
        return "";
    }

    const soon = Number(days) <= 7;
    const text = Number(days) === 0
        ? "reports today"
        : `reports in ${days} day${Number(days) === 1 ? "" : "s"}`;

    return `<div class="trend-earnings ${soon ? "soon" : ""}">${escapeHtml(text)}</div>`;
}


function renderTrendTile(trend) {
    const dayPercent = trend["1d"];
    const directionClass = trendDirectionClass(dayPercent);
    const strokeColor = dayPercent === null || dayPercent === undefined
        ? "#7f8896"
        : (Number(dayPercent) >= 0 ? "#4ec98a" : "#f0716f");

    return `
        <article class="trend-tile" data-ticker="${trend.ticker}" tabindex="0">
            <div class="trend-tile-top">
                <span class="trend-sym">${tickerTooltip(trend.ticker)}</span>
                <span class="trend-day num ${directionClass}">${signedPercent(dayPercent)}</span>
            </div>
            <div class="trend-price num" data-price-symbol="${trend.ticker}">${priceText(trend.current_price)}</div>
            <svg class="trend-spark" viewBox="0 0 130 30" preserveAspectRatio="none" aria-hidden="true">
                <polyline points="${sparklinePoints(trend)}" fill="none" stroke="${strokeColor}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"></polyline>
            </svg>
            ${earningsLine(trend)}
            <div class="trend-detail">
                ${trendDetailRow("1D", trend["1d"], trend["1d_dollar"])}
                ${trendDetailRow("5D", trend["5d"], trend["5d_dollar"])}
                ${trendDetailRow("2W", trend["2w"], trend["2w_dollar"])}
                ${trendDetailRow("1M", trend["1m"], trend["1m_dollar"])}
                ${trendDetailRow("YTD", trend.ytd, trend.ytd_dollar)}
            </div>
        </article>
    `;
}

/**
 * Reconstruct an approximate price path from the timeframe percentage changes the backend already returns.
 * Past prices are backed out of each move (ytd, 1m, 2w, 5d, 1d) and plotted left-to-right up to the current price, giving a momentum sparkline without any extra market-data calls.
 */
function sparklinePoints(trend) {
    const now = Number(trend.current_price);

    if (!Number.isFinite(now) || now <= 0) {
        return "0,15 130,15";
    }

    const changes = [trend.ytd, trend["1m"], trend["2w"], trend["5d"], trend["1d"], 0];
    const prices = changes.map(change => {
        const percent = Number(change);
        return Number.isFinite(percent) ? now / (1 + percent / 100) : now;
    });

    const min = Math.min(...prices);
    const max = Math.max(...prices);
    const range = max - min || 1;
    const lastIndex = prices.length - 1;

    return prices.map((price, index) => {
        const x = (index / lastIndex) * 130;
        const y = 27 - ((price - min) / range) * 24;
        return `${x.toFixed(1)},${y.toFixed(1)}`;
    }).join(" ");
}

/**
 * Render one timeframe row inside an expanded trend tile, showing both percentage and dollar move.
 * The percentage carries the direction color while the dollar figure stays quiet for context.
 */
function trendDetailRow(label, percentValue, dollarValue) {
    const directionClass = trendDirectionClass(percentValue);
    return `
        <div class="trend-drow">
            <span class="trend-dlabel">${label}</span>
            <span class="num ${directionClass}">${signedPercent(percentValue)}</span>
            <span class="num trend-ddollar">${signedMoney(dollarValue)}</span>
        </div>
    `;
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
        const response = await apiFetch("/api/market/prices", { auth: true });

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
    newsList.innerHTML = visibleNews.map(item => {
        const quality = String(item.source_quality || "unrated").replaceAll("_", " ");
        const qualityClass = /reput|high|trust|verified/i.test(quality) ? "good" : "unrated";
        const why = item.why_it_matters || item.summary || "";
        return `
        <article class="news-card">
            <div class="news-meta-row">
                <span class="news-source">${escapeHtml(item.source || "Unknown source")}</span>
                <span class="news-dot">&middot;</span>
                <span class="news-date num">${escapeHtml(newsDateText(item.created_at))}</span>
                <span class="news-quality ${qualityClass}">${escapeHtml(quality)}</span>
            </div>
            <a class="news-headline" href="${escapeHtml(safeExternalUrl(item.url))}" target="_blank" rel="noopener noreferrer">${escapeHtml(item.headline)}</a>
            <div class="news-chip-row">
                ${(item.symbols || []).slice(0, 5).map(symbol => `<span class="news-tk">${tickerTooltip(symbol)}</span>`).join("")}
                ${(item.tags || []).slice(0, 5).map(tag => `<span class="news-tag">${escapeHtml(String(tag).replaceAll("_", " "))}</span>`).join("")}
            </div>
            ${why ? `<p class="news-why"><span class="news-why-label">Why it matters &mdash; </span>${escapeHtml(why)}</p>` : ""}
        </article>
        `;
    }).join("");

    toggleNewsButton.classList.toggle("hidden", news.length <= DEFAULT_NEWS_COUNT);
    toggleNewsButton.textContent = showAllNews ? "Show fewer" : "See more news";
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
        <div class="mt-hero">
            <span class="mt-label">Reasoned take</span>
            <h3 class="mt-hero-head">${escapeHtml(take.headline || "Market risk check")}</h3>
            <p class="mt-hero-body">${escapeHtml(take.reasoned_take || take.summary || "Use this as context, not a prediction.")}</p>
        </div>
        <div class="mt-two">
            <article class="mt-card">
                <span class="mt-label muted">Market mood</span>
                <strong class="mt-stat">${escapeHtml(take.market_mood || "Mixed")}</strong>
                <p class="mt-explainer">${escapeHtml(marketMoodExplanation(take.market_mood || "Mixed"))}</p>
            </article>
            <article class="mt-card">
                <span class="mt-label muted">CSP stance</span>
                <strong class="mt-stat mt-stat-gold">${escapeHtml(take.csp_stance || "Selective")}</strong>
                <p class="mt-explainer">${escapeHtml(cspStanceExplanation(take.csp_stance || "Selective"))}</p>
            </article>
        </div>
        <div class="mt-two">
            <article class="mt-card mt-do">
                <span class="mt-label mt-label-pos">Do this</span>
                <p class="mt-body">${escapeHtml(take.action || "Prioritize clean candidates.")}</p>
            </article>
            <article class="mt-card mt-avoid">
                <span class="mt-label mt-label-neg">Avoid this</span>
                <p class="mt-body">${escapeHtml(take.avoid || "Do not force trades for premium.")}</p>
            </article>
        </div>
        <article class="mt-card mt-wide">
            <span class="mt-label muted">Your portfolio overall</span>
            <p class="mt-body">${annotateTickers(take.portfolio_take || "No current positions were available to review.")}</p>
        </article>
        <div class="mt-two">
            <article class="mt-card">
                <span class="mt-label muted">Selling puts</span>
                <p class="mt-body">${annotateTickers(take.csp_take || "Keep using the hard filters.")}</p>
            </article>
            <article class="mt-card">
                <span class="mt-label muted">Your covered calls</span>
                <p class="mt-body">${annotateTickers(take.covered_call_take || "No covered call view was available.")}</p>
            </article>
        </div>
        <div class="mt-two">
            <article class="mt-card">
                <span class="mt-label muted">Your shares</span>
                <p class="mt-body">${annotateTickers(take.stock_take || "No share view was available.")}</p>
            </article>
            <article class="mt-card">
                <span class="mt-label muted">Latest recommendations</span>
                <p class="mt-body">${annotateTickers(take.recommendation_take || "No recent recommendation run was available to compare.")}</p>
            </article>
        </div>
        ${companyNotes.length ? `
            <h3 class="mt-heading">Companies to watch</h3>
            <div class="mt-notes">
                ${companyNotes.map(note => `
                    <article class="mt-note">
                        <strong>${tickerTooltip(note.ticker || "Ticker")}</strong>
                        <p>${escapeHtml(note.note || "")}</p>
                    </article>
                `).join("")}
            </div>
        ` : ""}
        ${scenarios.length ? `
            <h3 class="mt-heading">Next few weeks</h3>
            <ul class="mt-scenarios">
                ${scenarios.map(scenario => `<li>${escapeHtml(scenario)}</li>`).join("")}
            </ul>
        ` : ""}
        <div class="mt-glossary">
            <span class="mt-label muted">Hover terms:</span>
            ${renderGlossaryChips(glossaryTerms)}
        </div>
    `;
}
