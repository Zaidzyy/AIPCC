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

/**
 * Generate a report. Five LLM sections run concurrently on the backend, so
 * this is a long request — the default axios timeout of none is intentional.
 * It answers 502 with a structured detail when every section fails.
 */
export async function generate({ documentId, reportName, classification }) {
  const { data } = await apiClient.post("/generate_report", {
    document_id: documentId,
    report_name: reportName,
    classification,
  });
  return data;
}

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
