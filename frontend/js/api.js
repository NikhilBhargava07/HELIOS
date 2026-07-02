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
 * This wrapper is intentionally thin today, but it is the future place to attach Cognito auth headers after Google login is added.
 */
function apiFetch(path, options = {}) {
    return fetch(apiUrl(path), options);
}
