/** Coordinate candidate discard and Alpaca paper-order actions. */

/**
 * Name one candidate in plain text for a toast.
 * The active strategy supplies the wording, so a call is never announced as a put.
 */
function orderLabelFor(candidate) {
    const view = strategyView(currentStrategyKey);
    return candidate && view.orderLabel ? view.orderLabel(candidate) : null;
}

async function submitDecision(action, candidateIdentifier) {
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
                contract_symbol: candidateIdentifier,
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
function removeCandidateFromPool(identifier) {
    candidatePool = candidatePool.filter(candidate => candidateId(candidate) !== identifier);
    renderRecsCandidates();
}

async function discardCandidate(clickedButton) {
    const identifier = clickedButton.dataset.contract;
    const card = clickedButton.closest(".rec-featured, .rec-alt");
    const recorded = await submitDecision("discard", identifier);

    if (!recorded) {
        return;
    }

    if (card) {
        card.classList.add("discarding");
        setTimeout(() => removeCandidateFromPool(identifier), 180);
    } else {
        removeCandidateFromPool(identifier);
    }
}

async function placeCandidate(clickedButton) {
    const identifier = clickedButton.dataset.contract;
    const card = clickedButton.closest(".rec-featured, .rec-alt");
    const candidate = candidateById(identifier);
    const originalButtonText = clickedButton.textContent;

    clickedButton.disabled = true;
    clickedButton.textContent = "Placing...";

    const result = await submitDecision("place_paper_order", identifier);

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

        // A rejected order can mean buying power moved, so re-check what is on screen rather than rescanning it.
        if (result.refresh_recommendations) {
            candidatePool = candidatesWithinLimits(
                candidatePool,
                result.dashboard?.capital?.effective_available_csp_capital,
            );
            renderRecsMetrics(result.dashboard);
            renderRecsCandidates();
        }

        return;
    }

    // Placing an order spends buying power, so keep the recommendations the user is weighing and drop only
    // the ones the account can no longer cash-secure. Rescanning here would replace them mid-decision.
    const remaining = candidatePool.filter(pooled => candidateId(pooled) !== identifier);
    const stillAffordable = candidatesWithinLimits(
        remaining,
        result.dashboard?.capital?.effective_available_csp_capital,
    );
    const droppedForCash = remaining.length - stillAffordable.length;
    const droppedNote = droppedForCash
        ? ` ${droppedForCash} other ${droppedForCash === 1 ? "candidate no longer fits" : "candidates no longer fit"} your buying power.`
        : "";

    showToast(
        result.duplicate_prevented ? "Paper order already placed" : "Paper order placed",
        (result.duplicate_prevented
            ? `The earlier ${candidate?.tickerSymbol || identifier} order was found, so HELIOS did not submit a duplicate.`
            : `${orderLabelFor(candidate) || identifier} submitted to Alpaca (${result.alpaca_order?.status || "submitted"}).`)
            + droppedNote,
    );

    renderRecsMetrics(result.dashboard);
    const settlePool = () => {
        candidatePool = stillAffordable;
        renderRecsCandidates();
    };

    if (card) {
        card.classList.add("discarding");
        setTimeout(settlePool, 180);
    } else {
        settlePool();
    }
}
