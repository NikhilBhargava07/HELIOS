/** Shared API URL helper for the deployed HELIOS frontend. */

const API_BASE_URL = "https://ofow6dmpv8.execute-api.us-east-1.amazonaws.com";

/** Build a full API Gateway URL from an app route like /api/health. */
function apiUrl(path) {
    if (path.startsWith("http")) {
        return path;
    }

    const normalizedPath = path.startsWith("/") ? path : `/${path}`;
    return `${API_BASE_URL}${normalizedPath}`;
}

/** Fetch from the deployed HELIOS API. */
function apiFetch(path, options = {}) {
    return fetch(apiUrl(path), options);
}
