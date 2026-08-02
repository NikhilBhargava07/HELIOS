/** Coordinate candidate discard and Alpaca paper-order actions. */

async function submitDecision(action, contractSymbol) {
    if (!currentRecommendationRunId) {
        recommendationStatus.textContent = "Run recommendations before recording a decision.";
        return false;
    }

    recommendationStatus.textContent = "Recording decision...";

    try {
        const response = await apiFetch("/api/decisions", {
            auth: true,
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
                recommendationStatus.textContent = data.duplicate_prevented
                    ? `This Alpaca paper order was already recorded (${data.alpaca_order?.status || "submitted"}).`
                    : `Alpaca paper order submitted (${data.alpaca_order?.status || "submitted"}).`;
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
 * Remove a handled candidate from the pool and re-render the featured/alternate layout.
 * When the featured candidate leaves, the next-best candidate is promoted into its place automatically.
 */
function removeCandidateFromPool(contractSymbol) {
    candidatePool = candidatePool.filter(candidate => candidate.contractSymbol !== contractSymbol);
    renderRecsCandidates();
}

async function discardCandidate(clickedButton) {
    const contractSymbol = clickedButton.dataset.contract;
    const card = clickedButton.closest(".rec-featured, .rec-alt");
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
    const card = clickedButton.closest(".rec-featured, .rec-alt");
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
        result.duplicate_prevented ? "Paper order already placed" : "Paper order placed",
        result.duplicate_prevented
            ? `The earlier ${candidate?.tickerSymbol || contractSymbol} order was found, so HELIOS did not submit a duplicate.`
            : `${candidate?.tickerSymbol || contractSymbol} ${money(candidate?.strike || 0)} put submitted to Alpaca (${result.alpaca_order?.status || "submitted"}).`,
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
