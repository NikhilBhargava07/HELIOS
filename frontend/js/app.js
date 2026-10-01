/** Wire navigation and user-interface events after shared scripts load. */

/**
 * Show one top-level page panel and run the refresh behavior that page needs.
 * Capital starts live portfolio polling, while other pages stop hidden timers so the app does not keep making unnecessary API calls.
 */
function showTab(tabName) {
    const requestedTab = tabName;

    if (requestedTab !== "home" && !isSignedIn()) {
        window.location.hash = "#home";
        tabName = "home";
        showToast("Sign in required", "Please sign in before opening the HELIOS dashboard.", "error");
    }

    panels.forEach(panel => {
        panel.classList.toggle("active", panel.dataset.panel === tabName);
    });

    navLinks.forEach(link => {
        link.classList.toggle("active", link.dataset.tab === tabName);
    });

    closeExplore();

    if (tabName === "capital") {
        loadDashboard();
        startDashboardRefresh();
    } else {
        stopDashboardRefresh();
    }

    if (tabName === "profile") {
        loadProfile();
    }

    if (tabName === "trends") {
        return;
    }

    stopPriceRefresh();
}

window.showTab = showTab;

if (button) {
    button.addEventListener("click", () => {
        showTab("recommendations");
        loadRecommendations();
    });
}

/**
 * Switch which strategy the next scan will run.
 * Candidates already on screen were scanned under the previous strategy's rules, so they are
 * cleared rather than relabeled: showing a put's numbers under a covered call heading would lie.
 */
function selectStrategy(tabKey) {
    if (tabKey === activeTab) {
        return;
    }

    activeTab = tabKey;

    strategyTabs.forEach(tab => {
        const selected = tab.dataset.strategy === tabKey;
        tab.classList.toggle("active", selected);
        tab.setAttribute("aria-selected", String(selected));
    });

    showHighlightsTab(tabKey === HIGHLIGHTS_TAB);

    if (tabKey === HIGHLIGHTS_TAB) {
        if (strategySubhead) {
            strategySubhead.textContent = HIGHLIGHTS_SUBHEAD;
        }
        loadDailyHighlights();
        return;
    }

    // Candidates on screen were scanned under the previous strategy's rules, so they are
    // cleared rather than relabelled: showing a put's numbers under a call heading would lie.
    activeStrategyKey = tabKey;
    const view = strategyView(tabKey);

    if (strategySubhead) {
        strategySubhead.textContent = view.subhead;
    }

    currentRecommendationRunId = null;
    candidatePool = [];
    recommendedContract = null;
    candidateList.innerHTML = "";
    const metricsEl = document.querySelector("#recs-metrics");
    if (metricsEl) {
        metricsEl.classList.add("empty");
        metricsEl.innerHTML = "";
    }
    reviewEl.classList.add("empty");
    reviewEl.textContent = `Run the scan to see the agent's ${view.label.toLowerCase()} review.`;
    recommendationStatus.textContent = `Ready to run a ${view.scanLabel}.`;
}


/**
 * Swap the page between today's saved picks and a live strategy scan.
 * Only one belongs on screen at a time: the picks are a briefing, and the scan area is a workspace.
 */
function showHighlightsTab(showHighlights) {
    if (highlightsEl) {
        highlightsEl.classList.toggle("tab-hidden", !showHighlights);
    }

    document.querySelectorAll("#recs-metrics, #agent-review, #candidate-list")
        .forEach(element => element.classList.toggle("tab-hidden", showHighlights));

    // Nothing to scan on the picks tab, so the button that starts one is put away.
    if (button) {
        button.classList.toggle("tab-hidden", showHighlights);
    }

    if (showHighlights) {
        recommendationStatus.textContent = "";
    }
}

strategyTabs.forEach(tab => {
    tab.addEventListener("click", () => selectStrategy(tab.dataset.strategy));
});
trendsButton.addEventListener("click", loadTrends);

// The earnings table filters and searches in place; nothing here refetches.
if (toggleEarningsButton) {
    toggleEarningsButton.addEventListener("click", () => {
        showAllEarnings = !showAllEarnings;
        renderEarnings();
    });
}

if (earningsList) {
    earningsList.addEventListener("click", (event) => {
        const pill = event.target.closest("[data-earnings-filter]");

        if (pill) {
            earningsFilter = pill.dataset.earningsFilter;
            showAllEarnings = false;
            renderEarnings();
        }
    });

    earningsList.addEventListener("input", (event) => {
        if (event.target.id !== "earnings-search") {
            return;
        }

        earningsSearch = event.target.value;
        showAllEarnings = false;
        renderEarnings();
        // Redrawing replaces the input, so the caret is put back where it was.
        const box = document.querySelector("#earnings-search");
        if (box) {
            box.focus();
            box.setSelectionRange(box.value.length, box.value.length);
        }
    });
}
newsButton.addEventListener("click", loadNews);
summarizeMarketButton.addEventListener("click", loadMarketTake);
/**
 * Open the full-screen Explore menu over the current page.
 * The overlay uses CSS transitions instead of heavy blur effects so navigation feels smooth without extra rendering cost.
 */
function openExplore() {
    if (!isSignedIn()) {
        showToast("Sign in required", "Please sign in before exploring HELIOS.", "error");
        return;
    }

    document.body.classList.add("explore-open");
    exploreOverlay.classList.remove("hidden");
    requestAnimationFrame(() => exploreOverlay.classList.add("visible"));
    exploreOverlay.setAttribute("aria-hidden", "false");
}

/**
 * Close the Explore overlay after its fade-out animation completes.
 * The short delay lets the transition finish before the overlay becomes hidden and non-interactive.
 */
function closeExplore() {
    exploreOverlay.classList.remove("visible");
    document.body.classList.remove("explore-open");
    exploreOverlay.setAttribute("aria-hidden", "true");
    setTimeout(() => {
        if (!exploreOverlay.classList.contains("visible")) {
            exploreOverlay.classList.add("hidden");
        }
    }, 220);
}

exploreDashboardButton.addEventListener("click", openExplore);
exploreDashboardSecondaryButton?.addEventListener("click", openExplore);
closeExploreButton.addEventListener("click", closeExplore);
document.querySelectorAll(".topbar-link, .topbar-brand").forEach(link => {
    link.addEventListener("click", () => showTab(link.dataset.tab));
});

exploreOverlay.addEventListener("click", (event) => {
    const clickedLink = event.target.closest(".nav-link");

    if (!clickedLink) {
        return;
    }

    showTab(clickedLink.dataset.tab);

    // Returning to recommendations keeps the results already on screen; only a first visit scans automatically.
    if (clickedLink.dataset.load === "earnings" && !latestEarnings.length) {
        loadEarnings();
    }

    if (clickedLink.dataset.load === "recommendations") {
        loadDailyHighlights();
    }

});


toggleTrendsButton.addEventListener("click", () => {
    showAllTrends = !showAllTrends;
    renderTrends(latestTrends);
});

// Trends page: filter pills, sort toggle, and click-to-expand tiles.
trendList.addEventListener("click", (event) => {
    const filterButton = event.target.closest("[data-filter]");
    if (filterButton) {
        trendFilter = filterButton.dataset.filter;
        showAllTrends = false;
        renderTrends(latestTrends);
        return;
    }

    const sortButton = event.target.closest("[data-sort-toggle]");
    if (sortButton) {
        trendSort = trendSort === "move" ? "default" : "move";
        renderTrends(latestTrends);
        return;
    }

    const tile = event.target.closest(".trend-tile");
    if (tile) {
        tile.classList.toggle("expanded");
    }
});

toggleNewsButton.addEventListener("click", () => {
    showAllNews = !showAllNews;
    renderNews(latestNews);
});

// The highlights panel has its own two actions: re-check a saved pick, then place the re-checked one.
if (highlightsEl) {
    highlightsEl.addEventListener("click", (event) => {
        const clickedButton = event.target.closest("button[data-action]");

        if (!clickedButton) {
            return;
        }

        if (clickedButton.dataset.action === "toggle_pick_detail") {
            const card = clickedButton.closest(".dh-pick");
            const opened = card.classList.toggle("expanded");
            clickedButton.textContent = opened ? "Hide" : "Why this";
        }

        if (clickedButton.dataset.action === "recheck_highlight") {
            recheckHighlight(clickedButton);
        }

        if (clickedButton.dataset.action === "place_highlight") {
            placeHighlight(clickedButton);
        }
    });
}

candidateList.addEventListener("click", (event) => {
    const clickedButton = event.target.closest("button[data-action]");

    if (!clickedButton) {
        // Tapping an alternate card body toggles its detail panel (touch fallback for hover).
        const alternateCard = event.target.closest(".rec-alt");

        if (alternateCard) {
            alternateCard.classList.toggle("expanded");
        }

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
/**
 * Read the browser hash and map it to a valid HELIOS page.
 * This lets direct reloads of links like #capital or #news reopen the correct panel instead of always showing Home.
 */
function tabFromHash() {
    const hashTab = window.location.hash.replace("#", "");
    const hasPanel = Array.from(panels).some(panel => panel.dataset.panel === hashTab);
    return hasPanel ? hashTab : "home";
}

/**
 * Keep the visible page synchronized with the current browser URL.
 * Hash changes, reloads, and back/forward navigation all pass through this small routing helper.
 */
function syncTabFromLocation() {
    showTab(tabFromHash());
}

window.addEventListener("hashchange", syncTabFromLocation);

// Give the sticky topbar a hairline + backdrop once the page scrolls away from the top.
const appTopbar = document.querySelector(".app-topbar");
window.addEventListener("scroll", () => {
    if (appTopbar) {
        appTopbar.classList.toggle("scrolled", window.scrollY > 8);
    }
}, { passive: true });

/**
 * Start HELIOS after Cognito has had a chance to process the Google redirect.
 * Without this await, the app can render as "signed in" navigation before the profile check has confirmed whether the user still needs onboarding.
 */
async function bootstrapApp() {
    await initializeAuth();
    syncTabFromLocation();

    // New users (or anyone who hasn't connected a broker) are gated on the sign-up screen.
    if (isSignedIn() && typeof checkOnboarding === "function") {
        await checkOnboarding();
    }
}

bootstrapApp();
