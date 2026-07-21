/**
 * Profile dropdown, Profile page, and broker-connection modal.
 *
 * The dropdown opens from the navbar avatar and offers Profile, Settings, and
 * Sign out. Profile navigates to the #profile page, which shows identity from
 * the stored Cognito session immediately and then fills broker status from
 * GET /api/profile. Settings and "Manage keys" open the connect-broker modal,
 * which posts to /api/profile/broker.
 */

const profileMenu = document.querySelector("#profile-menu");
const profileMenuHead = document.querySelector("#profile-menu-head");
const profileContent = document.querySelector("#profile-content");
const brokerModal = document.querySelector("#broker-modal");
const brokerForm = document.querySelector("#broker-form");
const brokerError = document.querySelector("#broker-error");

// Last profile payload seen, so "Manage keys" can prefill the broker form.
let latestProfile = null;

/** Turn a broker id into a friendly label for display. */
function brokerLabel(broker) {
    const labels = { alpaca: "Alpaca (paper)" };
    return labels[String(broker || "").toLowerCase()] || (broker || "—");
}

/** Mask a broker API key so only its ends are visible. */
function maskKey(key) {
    const value = String(key || "");
    if (value.length <= 8) {
        return value || "—";
    }
    return `${value.slice(0, 4)}••••••••${value.slice(-3)}`;
}

/** Format a stored ISO timestamp into a short profile date. */
function profileDate(value) {
    if (!value) {
        return "—";
    }
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) {
        return String(value);
    }
    return date.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

/** Clean up an Alpaca account status string (e.g. "AccountStatus.ACTIVE") for display. */
function prettyStatus(status) {
    const value = String(status || "").replace(/^AccountStatus\./, "").replace(/_/g, " ").trim().toLowerCase();
    return value ? value.charAt(0).toUpperCase() + value.slice(1) : "—";
}

/** Show or hide the avatar dropdown, refreshing its header when opening. */
function toggleProfileMenu() {
    if (!profileMenu) {
        return;
    }
    const willOpen = profileMenu.classList.contains("hidden");
    if (willOpen) {
        renderProfileMenuHead();
    }
    profileMenu.classList.toggle("hidden", !willOpen);
}

/** Hide the avatar dropdown. */
function closeProfileMenu() {
    profileMenu?.classList.add("hidden");
}

/** Fill the dropdown header with the signed-in user's initial, name, and email. */
function renderProfileMenuHead() {
    const user = getSignedInUser();
    if (!profileMenuHead || !user) {
        return;
    }
    const name = user.name || user.email || "Account";
    const initial = name.trim().charAt(0).toUpperCase();
    profileMenuHead.innerHTML = `
        <span class="profile-avatar">${escapeHtml(initial)}</span>
        <div class="profile-menu-id">
            <div class="profile-menu-name">${escapeHtml(user.name || "Account")}</div>
            <div class="profile-menu-email">${escapeHtml(user.email || "")}</div>
        </div>
    `;
}

/**
 * Load the Profile page: render identity from the stored session right away,
 * then attempt to fill broker status from the backend and degrade gracefully.
 */
async function loadProfile() {
    if (!profileContent || !isSignedIn()) {
        return;
    }

    const user = getSignedInUser();
    renderProfile({
        profile: { name: user?.name, email: user?.email, broker_connected: false },
        needs_onboarding: true,
    });

    try {
        const response = await apiFetch("/api/profile", { auth: true });
        if (!response.ok) {
            throw new Error(`Request failed with status ${response.status}`);
        }
        const data = await response.json();
        latestProfile = data.profile || null;
        renderProfile(data);
        if (data.needs_onboarding) {
            showSignup(data.profile);
        }
    } catch (error) {
        renderProfile({
            profile: { name: user?.name, email: user?.email, broker_connected: false },
            needs_onboarding: true,
            errored: true,
        });
        showSignup(user);
        showSignupError("HELIOS could not confirm your account setup. Reconnect your broker here to continue.");
    }
}

/** Render the Profile page: identity card plus broker-connection card. */
function renderProfile(data) {
    if (!profileContent) {
        return;
    }

    const profile = data.profile || {};
    const user = getSignedInUser();
    const name = profile.name || user?.name || "Account";
    const email = profile.email || user?.email || "";
    const initial = String(name || "?").trim().charAt(0).toUpperCase();
    const connected = Boolean(profile.broker_connected);

    profileContent.innerHTML = `
        <div class="profile-card profile-identity">
            <span class="profile-avatar lg">${escapeHtml(initial)}</span>
            <div class="profile-identity-text">
                <div class="profile-name">${escapeHtml(name)}</div>
                <div class="profile-email">${escapeHtml(email)}</div>
            </div>
            <span class="profile-provider">Google</span>
        </div>
        <div class="profile-card">
            <div class="profile-broker-head">
                <span class="profile-broker-title">Broker connection</span>
                <span class="profile-status ${connected ? "on" : "off"}">${connected ? "Connected" : "Not connected"}</span>
            </div>
            ${connected ? `
                <div class="profile-row"><span class="profile-lbl">Broker</span><span class="profile-val">${escapeHtml(brokerLabel(profile.broker))}</span></div>
                ${profile.broker_account_number ? `<div class="profile-row"><span class="profile-lbl">Account</span><span class="profile-val mono">${escapeHtml(profile.broker_account_number)}</span></div>` : ""}
                ${profile.broker_account_status ? `<div class="profile-row"><span class="profile-lbl">Status</span><span class="profile-val">${escapeHtml(prettyStatus(profile.broker_account_status))}</span></div>` : ""}
                <div class="profile-row"><span class="profile-lbl">API key</span><span class="profile-val mono">${escapeHtml(maskKey(profile.broker_api_key))}</span></div>
                <div class="profile-row"><span class="profile-lbl">Secret key</span><span class="profile-val muted">Stored securely &middot; hidden</span></div>
                <div class="profile-row"><span class="profile-lbl">Connected on</span><span class="profile-val mono">${escapeHtml(profileDate(profile.created_at))}</span></div>
                <div class="profile-row"><span class="profile-lbl">Last updated</span><span class="profile-val mono">${escapeHtml(profileDate(profile.updated_at))}</span></div>
                <div class="profile-broker-actions"><button type="button" class="profile-manage" data-open-broker>Manage keys</button></div>
            ` : `
                <p class="profile-connect-note">${data.errored ? "Couldn't load your broker status right now. " : ""}Connect a broker to place trades on your own account.</p>
                <div class="profile-broker-actions"><button type="button" class="profile-manage" data-open-broker>Connect Alpaca</button></div>
            `}
        </div>
    `;
}

/** Open the connect-broker modal, prefilling broker and API key when updating. */
function openBrokerModal(profile) {
    if (!brokerModal) {
        return;
    }
    const brokerSelect = document.querySelector("#broker-select");
    const apiKeyInput = document.querySelector("#broker-api-key");
    const secretInput = document.querySelector("#broker-secret-key");

    brokerError?.classList.add("hidden");
    if (brokerSelect && profile?.broker) {
        brokerSelect.value = profile.broker;
    }
    if (apiKeyInput) {
        apiKeyInput.value = profile?.broker_api_key || "";
    }
    if (secretInput) {
        secretInput.value = "";
    }

    brokerModal.classList.remove("hidden");
}

/** Hide the connect-broker modal. */
function closeBrokerModal() {
    brokerModal?.classList.add("hidden");
}

/** Show an inline error inside the broker modal. */
function showBrokerError(message) {
    if (!brokerError) {
        return;
    }
    brokerError.textContent = message;
    brokerError.classList.remove("hidden");
}

// Extract the most useful backend error text so profile setup failures explain what actually went wrong.
async function brokerErrorMessage(response) {
    try {
        const data = await response.json();

        if (data?.detail) {
            return data.detail;
        }
    } catch {
        // If the response is not JSON, fall through to a status-based explanation.
    }

    if (response.status === 401 || response.status === 403) {
        return "Your login session expired. Sign out, sign in again, then reconnect Alpaca.";
    }

    return "Couldn't save your broker keys. Please try again.";
}

// Dropdown item actions: Profile navigates, Settings opens the form, Sign out logs out.
profileMenu?.addEventListener("click", (event) => {
    const item = event.target.closest("[data-profile-action]");
    if (!item) {
        return;
    }

    const action = item.dataset.profileAction;
    closeProfileMenu();

    if (action === "profile") {
        window.location.hash = "#profile";
    } else if (action === "settings") {
        openBrokerModal(latestProfile);
    } else if (action === "signout") {
        logout();
    }
});

// Close the dropdown when clicking anywhere outside the avatar/menu wrapper.
document.addEventListener("click", (event) => {
    if (!profileMenu || profileMenu.classList.contains("hidden")) {
        return;
    }
    if (event.target.closest(".profile-wrap")) {
        return;
    }
    closeProfileMenu();
});

// "Manage keys" / "Connect" buttons on the Profile page open the broker modal.
profileContent?.addEventListener("click", (event) => {
    if (event.target.closest("[data-open-broker]")) {
        openBrokerModal(latestProfile);
    }
});

// Broker modal close controls (X, Cancel, and backdrop click).
document.querySelector("#broker-modal-close")?.addEventListener("click", closeBrokerModal);
document.querySelector("#broker-cancel")?.addEventListener("click", closeBrokerModal);
brokerModal?.addEventListener("click", (event) => {
    if (event.target === brokerModal) {
        closeBrokerModal();
    }
});

/** POST broker credentials to the backend, returning the saved profile payload or throwing a readable error. */
async function saveBrokerCredentials(broker, apiKey, secretKey) {
    const response = await apiFetch("/api/profile/broker", {
        auth: true,
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ broker, broker_api_key: apiKey, broker_secret_key: secretKey }),
    });
    if (!response.ok) {
        throw new Error(await brokerErrorMessage(response));
    }
    return response.json();
}

// Submit the broker credentials to the backend.
brokerForm?.addEventListener("submit", async (event) => {
    event.preventDefault();

    const broker = document.querySelector("#broker-select").value;
    const apiKey = document.querySelector("#broker-api-key").value.trim();
    const secretKey = document.querySelector("#broker-secret-key").value.trim();

    if (!apiKey || !secretKey) {
        showBrokerError("Enter both your API key and secret key.");
        return;
    }

    const submitButton = document.querySelector("#broker-submit");
    brokerError?.classList.add("hidden");
    submitButton.disabled = true;
    submitButton.textContent = "Connecting...";

    try {
        const data = await saveBrokerCredentials(broker, apiKey, secretKey);
        latestProfile = data.profile || null;
        closeBrokerModal();
        showToast("Broker connected", "Your broker keys are saved.");
        renderProfile(data);
    } catch (error) {
        showBrokerError(error.message || "Couldn't save your broker keys. Please try again.");
    } finally {
        submitButton.disabled = false;
        submitButton.textContent = "Connect broker";
    }
});


// ---- New-user sign-up gate (shown when GET /api/profile reports needs_onboarding) ----

const signupScreen = document.querySelector("#signup-screen");
const signupForm = document.querySelector("#signup-form");
const signupError = document.querySelector("#signup-error");

/** Show an inline error inside the sign-up screen. */
function showSignupError(message) {
    if (!signupError) {
        return;
    }
    signupError.textContent = message;
    signupError.classList.remove("hidden");
}

/** Show the full-screen sign-up gate, prefilling the email from the signed-in session. */
function showSignup(profile) {
    if (!signupScreen) {
        return;
    }
    const user = getSignedInUser();
    const email = profile?.email || user?.email || "";
    const emailField = document.querySelector("#signup-email");
    const accountEmail = document.querySelector("#signup-account-email");
    if (emailField) {
        emailField.textContent = email;
    }
    if (accountEmail) {
        accountEmail.textContent = email;
    }
    signupError?.classList.add("hidden");
    document.body.classList.add("onboarding");
    signupScreen.classList.remove("hidden");
}

/** Hide the sign-up gate. */
function hideSignup() {
    document.body.classList.remove("onboarding");
    signupScreen?.classList.add("hidden");
}

/**
 * Gate the app on the sign-up screen when the signed-in user hasn't connected a broker yet.
 * Runs after Google login and on load; a signed-in user stays gated until the backend confirms broker onboarding is complete.
 */
async function checkOnboarding() {
    if (!isSignedIn() || !signupScreen) {
        hideSignup();
        return;
    }

    try {
        const response = await apiFetch("/api/profile", { auth: true });
        if (!response.ok) {
            showSignup(getSignedInUser());
            showSignupError(await brokerErrorMessage(response));
            return;
        }
        const data = await response.json();
        latestProfile = data.profile || null;

        if (data.needs_onboarding) {
            showSignup(data.profile);
        } else {
            hideSignup();
        }
    } catch (error) {
        showSignup(getSignedInUser());
        showSignupError("HELIOS could not confirm your account setup. Refresh after signing in, or reconnect your broker here.");
    }
}

// Submit a new user's broker credentials to create their HELIOS account.
signupForm?.addEventListener("submit", async (event) => {
    event.preventDefault();

    const broker = document.querySelector("#signup-broker").value;
    const apiKey = document.querySelector("#signup-api-key").value.trim();
    const secretKey = document.querySelector("#signup-secret-key").value.trim();

    if (!apiKey || !secretKey) {
        showSignupError("Enter both your API key and secret key.");
        return;
    }

    const submitButton = document.querySelector("#signup-submit");
    signupError?.classList.add("hidden");
    submitButton.disabled = true;
    submitButton.textContent = "Creating account...";

    try {
        const data = await saveBrokerCredentials(broker, apiKey, secretKey);
        latestProfile = data.profile || null;
        hideSignup();
        showToast("Account created", "Your broker is connected. Welcome to HELIOS.");
        window.location.hash = "#recommendations";
    } catch (error) {
        showSignupError(error.message || "Couldn't create your account. Please try again.");
    } finally {
        submitButton.disabled = false;
        submitButton.textContent = "Create account and sign in";
    }
});

// "Switch account" signs out so the user can choose a different Google account.
document.querySelector("#signup-switch")?.addEventListener("click", logout);
