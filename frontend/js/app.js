/** Wire navigation and user-interface events after shared scripts load. */

/** Display one navigation panel and trigger tab-specific refresh behavior. */
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
function openExplore() {
    document.body.classList.add("explore-open");
    exploreOverlay.classList.remove("hidden");
    requestAnimationFrame(() => exploreOverlay.classList.add("visible"));
    exploreOverlay.setAttribute("aria-hidden", "false");
}

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
