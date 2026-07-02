/** Coordinate candidate discard and Alpaca paper-order actions. */

async function submitDecision(action, contractSymbol) {
    if (!currentRecommendationRunId) {
        recommendationStatus.textContent = "Run recommendations before recording a decision.";
        return false;
    }

    recommendationStatus.textContent = "Recording decision...";

    try {
        const response = await apiFetch("/api/decisions", {
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

/**
 * Remove a handled candidate and replace it in the same visible card position.
 * This lets discard and paper-place actions cycle through queued candidates without confusing ranking numbers.
 */
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
