/** Handle Cognito Hosted UI login, logout, and browser-side session state. */

// Public Cognito settings for HELIOS. The client id is intentionally safe to ship to a browser; no Google or Cognito client secret belongs here.
const AUTH_CONFIG = {
    domain: "https://us-east-1y0qpl0tn3.auth.us-east-1.amazoncognito.com",
    clientId: "vkgo23lfbtgmrv3roo28uhpg6",
    redirectUri: window.location.origin,
    scopes: "openid email profile",
};

// Storage keys are centralized so login, callback handling, and logout clear the same browser session data.
const AUTH_STORAGE = {
    verifier: "helios.pkce.verifier",
    state: "helios.oauth.state",
    tokens: "helios.auth.tokens",
    user: "helios.auth.user",
};

// Convert a normal string to URL-safe base64 for OAuth PKCE code challenges.
function base64UrlEncode(value) {
    return btoa(value)
        .replace(/\+/g, "-")
        .replace(/\//g, "_")
        .replace(/=+$/, "");
}

// Convert random bytes into a browser-safe OAuth string.
function randomUrlSafeString(byteCount = 32) {
    const randomBytes = new Uint8Array(byteCount);
    crypto.getRandomValues(randomBytes);
    return base64UrlEncode(String.fromCharCode(...randomBytes));
}

// Hash the PKCE verifier and convert it into the challenge Cognito expects during login.
async function pkceChallenge(verifier) {
    const encodedVerifier = new TextEncoder().encode(verifier);
    const digest = await crypto.subtle.digest("SHA-256", encodedVerifier);
    const digestBytes = new Uint8Array(digest);
    return base64UrlEncode(String.fromCharCode(...digestBytes));
}

// Decode a JWT payload so the UI can show the signed-in user's name or email.
function decodeJwtPayload(token) {
    const [, payload] = token.split(".");

    if (!payload) {
        return {};
    }

    const normalizedPayload = payload.replace(/-/g, "+").replace(/_/g, "/");
    const paddedPayload = normalizedPayload.padEnd(normalizedPayload.length + ((4 - normalizedPayload.length % 4) % 4), "=");
    return JSON.parse(atob(paddedPayload));
}

// Read the stored user profile from local storage, returning null when no valid login exists.
function getSignedInUser() {
    try {
        const storedUser = JSON.parse(localStorage.getItem(AUTH_STORAGE.user));

        if (!storedUser) {
            return null;
        }

        if (storedUser.expiresAt && storedUser.expiresAt <= Math.floor(Date.now() / 1000)) {
            clearAuthSession();
            return null;
        }

        return storedUser;
    } catch {
        return null;
    }
}

// Return true only when the browser has a non-expired Cognito user session.
function isSignedIn() {
    return Boolean(getSignedInUser());
}

// Store Cognito token response data and a small profile summary for simple UI display.
function storeAuthTokens(tokenPayload) {
    localStorage.setItem(AUTH_STORAGE.tokens, JSON.stringify(tokenPayload));

    if (tokenPayload.id_token) {
        const claims = decodeJwtPayload(tokenPayload.id_token);
        localStorage.setItem(AUTH_STORAGE.user, JSON.stringify({
            email: claims.email,
            name: claims.name || claims.given_name || claims.email,
            expiresAt: claims.exp,
        }));
    }
}

// Remove all local auth data so the browser no longer treats the user as signed in.
function clearAuthSession() {
    localStorage.removeItem(AUTH_STORAGE.tokens);
    localStorage.removeItem(AUTH_STORAGE.user);
    sessionStorage.removeItem(AUTH_STORAGE.verifier);
    sessionStorage.removeItem(AUTH_STORAGE.state);
}

// Update login/logout buttons and status text based on the current stored Cognito session.
function renderAuthState() {
    const signedInUser = getSignedInUser();
    const label = signedInUser ? "Sign out" : "Sign in / up";
    const status = signedInUser
        ? `Signed in as ${signedInUser.name || signedInUser.email}`
        : "Not signed in.";

    authButtons.forEach(authButton => {
        // The topbar auth control becomes an avatar (user initial) when signed in; the home button stays a text button.
        if (signedInUser && authButton.id === "auth-action") {
            const source = signedInUser.name || signedInUser.email || "?";
            authButton.textContent = source.trim().charAt(0).toUpperCase();
            authButton.setAttribute("aria-label", "Sign out");
            authButton.title = "Sign out";
        } else {
            authButton.textContent = label;
            authButton.setAttribute("aria-label", label);
            authButton.removeAttribute("title");
        }

        authButton.classList.toggle("signed-in", Boolean(signedInUser));
    });

    document.body.classList.toggle("signed-in", Boolean(signedInUser));
    document.body.classList.toggle("signed-out", !signedInUser);

    if (authStatus) {
        authStatus.textContent = status;
    }
}

// Send the user to Cognito Hosted UI using PKCE, which avoids putting any client secret in frontend code.
async function startLogin() {
    const verifier = randomUrlSafeString(64);
    const challenge = await pkceChallenge(verifier);
    const state = randomUrlSafeString(24);

    sessionStorage.setItem(AUTH_STORAGE.verifier, verifier);
    sessionStorage.setItem(AUTH_STORAGE.state, state);

    const params = new URLSearchParams({
        client_id: AUTH_CONFIG.clientId,
        response_type: "code",
        scope: AUTH_CONFIG.scopes,
        redirect_uri: AUTH_CONFIG.redirectUri,
        code_challenge_method: "S256",
        code_challenge: challenge,
        state,
        identity_provider: "Google",
    });

    window.location.assign(`${AUTH_CONFIG.domain}/oauth2/authorize?${params.toString()}`);
}

// Exchange Cognito's temporary authorization code for browser tokens after Google redirects back to HELIOS.
async function exchangeCodeForTokens(code) {
    const verifier = sessionStorage.getItem(AUTH_STORAGE.verifier);

    if (!verifier) {
        throw new Error("Missing login verifier. Please start sign-in again.");
    }

    const body = new URLSearchParams({
        grant_type: "authorization_code",
        client_id: AUTH_CONFIG.clientId,
        code,
        redirect_uri: AUTH_CONFIG.redirectUri,
        code_verifier: verifier,
    });

    const response = await fetch(`${AUTH_CONFIG.domain}/oauth2/token`, {
        method: "POST",
        headers: {
            "Content-Type": "application/x-www-form-urlencoded",
        },
        body,
    });

    if (!response.ok) {
        throw new Error(`Token exchange failed with status ${response.status}`);
    }

    return response.json();
}

// Remove OAuth query parameters from the URL after login so reloads do not retry the same one-time code.
function cleanAuthQueryParams() {
    const cleanUrl = `${window.location.origin}${window.location.pathname}${window.location.hash || ""}`;
    window.history.replaceState({}, document.title, cleanUrl);
}

// Handle Cognito's redirect back to HELIOS and turn the temporary code into a saved local session.
async function handleAuthCallback() {
    const params = new URLSearchParams(window.location.search);
    const code = params.get("code");
    const state = params.get("state");
    const error = params.get("error");

    if (error) {
        cleanAuthQueryParams();
        showToast("Login failed", params.get("error_description") || error, "error");
        return;
    }

    if (!code) {
        return;
    }

    const expectedState = sessionStorage.getItem(AUTH_STORAGE.state);

    if (!expectedState || expectedState !== state) {
        cleanAuthQueryParams();
        clearAuthSession();
        showToast("Login blocked", "The returned login state did not match. Please try again.", "error");
        return;
    }

    try {
        const tokenPayload = await exchangeCodeForTokens(code);
        storeAuthTokens(tokenPayload);
        cleanAuthQueryParams();
        renderAuthState();
        syncTabFromLocation();
        showToast("Signed in", "Google login is connected through Cognito.");

        if (typeof checkOnboarding === "function") {
            checkOnboarding();
        }
    } catch (error) {
        cleanAuthQueryParams();
        clearAuthSession();
        renderAuthState();
        showToast("Login failed", error.message, "error");
    }
}

// Send the user through Cognito logout and back to the HELIOS CloudFront site.
function logout() {
    clearAuthSession();
    renderAuthState();

    const params = new URLSearchParams({
        client_id: AUTH_CONFIG.clientId,
        logout_uri: AUTH_CONFIG.redirectUri,
    });

    window.location.assign(`${AUTH_CONFIG.domain}/logout?${params.toString()}`);
}

// Wire the auth buttons, process any returned login code, and draw the initial auth state.
function initializeAuth() {
    authButtons.forEach(authButton => {
        authButton.addEventListener("click", async () => {
            if (getSignedInUser()) {
                // The topbar avatar opens the profile dropdown; other auth buttons sign out.
                if (authButton.id === "auth-action" && typeof toggleProfileMenu === "function") {
                    toggleProfileMenu();
                    return;
                }
                logout();
                return;
            }

            try {
                await startLogin();
            } catch (error) {
                showToast("Sign in failed", error.message || "Unable to start Google sign-in.", "error");
            }
        });
    });

    renderAuthState();
    return handleAuthCallback();
}
