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
 * Fetch data from the HELIOS backend through the shared URL helper.
 * This stays intentionally thin until API Gateway/Lambda are configured to verify Cognito JWTs.
 * Adding Authorization too early triggers browser preflight/CORS behavior and can break currently public prototype routes.
 */
function apiFetch(path, options = {}) {
    return fetch(apiUrl(path), options);
}
