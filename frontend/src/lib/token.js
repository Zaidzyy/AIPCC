/**
 * JWT storage.
 *
 * Kept in its own module so `apiClient` can read the token without importing
 * the auth context, and the context can write it without importing the client.
 * Anything else would be a cycle.
 */

const STORAGE_KEY = "aipcc.token";

export const UNAUTHORIZED_EVENT = "aipcc:unauthorized";

export function getToken() {
  try {
    return localStorage.getItem(STORAGE_KEY);
  } catch {
    // Private browsing modes can throw on access rather than returning null.
    return null;
  }
}

export function setToken(token) {
  try {
    if (token) localStorage.setItem(STORAGE_KEY, token);
    else localStorage.removeItem(STORAGE_KEY);
  } catch {
    /* Storage unavailable — the session simply will not survive a reload. */
  }
}

export function clearToken() {
  setToken(null);
}
