import { apiClient } from "@/lib/apiClient";
import { filenameFromResponse } from "@/lib/download";

export async function list() {
  const { data } = await apiClient.get("/reports");
  return data;
}

export async function get(reportId) {
  const { data } = await apiClient.get(`/reports/${reportId}`);
  return data;
}

export async function status(reportId) {
  const { data } = await apiClient.get(`/reports/${reportId}/status`);
  return data;
}

/*
 * There is no `generate()` here any more. The browser generates over the SSE
 * stream in `lib/api/stream.js`, which cannot go through axios — axios buffers
 * the whole body before it resolves, which is exactly what a stream exists to
 * avoid. `POST /generate_report` still exists on the backend for n8n and other
 * API clients and is covered by the backend suite; nothing in this app calls
 * it, and keeping a wrapper nobody uses would only invite one.
 */

export async function remove(reportId) {
  await apiClient.delete(`/reports/${reportId}`);
}

export async function setClassification(reportId, classification) {
  const { data } = await apiClient.patch(`/reports/${reportId}/classification`, {
    classification,
  });
  return data;
}

/**
 * Download a report as a file.
 *
 * Returns the blob and the server's filename rather than saving it, so the
 * caller decides what to do with a failure — an error here arrives as JSON in
 * a blob, which is why `errorMessage` cannot read it and the caller shows a
 * generic message instead.
 */
export async function exportReport({ reportId, format }) {
  const response = await apiClient.get(`/reports/${reportId}/export`, {
    params: { format },
    responseType: "blob",
  });
  return {
    blob: response.data,
    filename: filenameFromResponse(response, `report.${format}`),
  };
}
