/** Wire navigation and user-interface events after shared scripts load. */

/**
 * Show one top-level page panel and run the refresh behavior that page needs.
 * Capital starts live portfolio polling, while other pages stop hidden timers so the app does not keep making unnecessary API calls.
 */
function showTab(tabName) {
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

    if (tabName === "trends") {
        return;
    }

    stopPriceRefresh();
    stopTrendMetricRotation();
}

window.showTab = showTab;

if (button) {
    button.addEventListener("click", () => {
        showTab("recommendations");
        loadRecommendations();
    });
}
trendsButton.addEventListener("click", loadTrends);
newsButton.addEventListener("click", loadNews);
summarizeMarketButton.addEventListener("click", loadMarketTake);
/**
 * Open the full-screen Explore menu over the current page.
 * The overlay uses CSS transitions instead of heavy blur effects so navigation feels smooth without extra rendering cost.
 */
function openExplore() {
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

    if (clickedLink.dataset.load === "recommendations") {
        loadRecommendations();
    }
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
syncTabFromLocation();

