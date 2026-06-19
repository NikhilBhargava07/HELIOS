/** Wire navigation and user-interface events after shared scripts load. */

/** Display one navigation panel and trigger tab-specific refresh behavior. */
function showTab(tabName) {
    panels.forEach(panel => {
        panel.classList.toggle("active", panel.dataset.panel === tabName);
    });

    navLinks.forEach(link => {
        link.classList.toggle("active", link.dataset.tab === tabName);
    });

    sidebar.classList.remove("open");

    if (tabName === "capital") {
        loadDashboard();
    }
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
