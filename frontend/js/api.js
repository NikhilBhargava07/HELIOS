/** Shared API URL helper for the deployed HELIOS frontend. */

const API_BASE_URL = "https://ofow6dmpv8.execute-api.us-east-1.amazonaws.com";

/**
 * Build the deployed API Gateway URL for a frontend request path.
 * Keeping this helper centralized means the rest of the UI can call routes like /api/dashboard without repeating the CloudFront/API Gateway base URL.
 */
function apiUrl(path) {
    if (path.startsWith("http")) {
        return path;
    }

    const normalizedPath = path.startsWith("/") ? path : `/${path}`;
    return `${API_BASE_URL}${normalizedPath}`;
}

/**
 * Read the Cognito ID token stored after Hosted UI login.
 * HELIOS uses the ID token for profile routes because it carries the user's email/name claims, while access tokens are mainly for API scopes.
 */
function getStoredIdToken() {
    try {
        const tokens = JSON.parse(localStorage.getItem("helios.auth.tokens") || "{}");
        return tokens.id_token || "";
    } catch {
        return "";
    }
}

/**
 * Fetch data from the HELIOS backend through the shared URL helper.
 * Pass { auth: true } for routes protected by API Gateway's Cognito JWT authorizer, such as profile and broker-key setup.
 */
function apiFetch(path, options = {}) {
    const { auth = false, ...fetchOptions } = options;
    const headers = new Headers(fetchOptions.headers || {});

    if (auth && !headers.has("Authorization")) {
        const idToken = getStoredIdToken();

        if (idToken) {
            headers.set("Authorization", `Bearer ${idToken}`);
        }
    }

    return fetch(apiUrl(path), { ...fetchOptions, headers });
}
