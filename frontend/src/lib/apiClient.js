import axios from "axios";

import { UNAUTHORIZED_EVENT, clearToken, getToken } from "@/lib/token";

export const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, "") || "http://localhost:8000";

export const apiClient = axios.create({
  baseURL: API_BASE_URL,
  headers: { Accept: "application/json" },
});

apiClient.interceptors.request.use((config) => {
  const token = getToken();
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

/** Login answers 401 for bad credentials — that is a form error, not a dead session. */
const isLoginRequest = (config) => config?.url?.includes("/auth/login");

apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401 && !isLoginRequest(error.config)) {
      clearToken();
      // The auth context listens for this and clears the user, which lets
      // ProtectedRoute redirect through the router. A `location.assign` here
      // would work too, but at the cost of a full page reload.
      window.dispatchEvent(new CustomEvent(UNAUTHORIZED_EVENT));
    }
    return Promise.reject(error);
  },
);

/**
 * Pull a displayable message out of an axios error.
 *
 * FastAPI answers with `detail`, which is a string for `HTTPException`, an
 * array for request-validation failures, and an object for the structured
 * 502 that `/generate_report` raises. All three reach the UI, so all three
 * are handled here rather than at each call site.
 */
export function errorMessage(error, fallback = "Something went wrong.") {
  if (!error) return fallback;

  const detail = error.response?.data?.detail;

  if (typeof detail === "string") return detail;

  if (Array.isArray(detail)) {
    const first = detail[0];
    if (!first) return fallback;
    const field = Array.isArray(first.loc) ? first.loc.at(-1) : null;
    return field ? `${field}: ${first.msg}` : first.msg;
  }

  if (detail && typeof detail === "object") {
    return detail.message || fallback;
  }

  if (error.code === "ERR_NETWORK") {
    return `Cannot reach the API at ${API_BASE_URL}. Is the backend running?`;
  }

  return error.message || fallback;
}

/** The structured payload `/generate_report` returns with its 502, if present. */
export function errorDetail(error) {
  const detail = error?.response?.data?.detail;
  return detail && typeof detail === "object" && !Array.isArray(detail) ? detail : null;
}
