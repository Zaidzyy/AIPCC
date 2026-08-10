import { apiClient } from "@/lib/apiClient";
import { filenameFromResponse } from "@/lib/download";

export async function list(reportId) {
  const { data } = await apiClient.get(`/reports/${reportId}/shares`);
  return data;
}

/**
 * Mint a link. The response is the only time the token exists — the list
 * endpoint never returns it again, so the dialog has to show it now.
 */
export async function create({ reportId, expiresInHours, label, justification }) {
  const { data } = await apiClient.post(`/reports/${reportId}/shares`, {
    expires_in_hours: expiresInHours,
    label: label || null,
    justification: justification || null,
  });
  return data;
}

export async function revoke(shareId) {
  const { data } = await apiClient.delete(`/shares/${shareId}`);
  return data;
}

/**
 * Read a shared report. Called from the public route, where there is no
 * session — the request interceptor may still attach a stale token from a
 * previous login on this browser, and the endpoint ignores it either way.
 */
export async function getShared(token) {
  const { data } = await apiClient.get(`/share/${token}`);
  return data;
}

export async function exportShared({ token, format }) {
  const response = await apiClient.get(`/share/${token}/export`, {
    params: { format },
    responseType: "blob",
  });
  return {
    blob: response.data,
    filename: filenameFromResponse(response, `report.${format}`),
  };
}
