import { apiClient } from "@/lib/apiClient";

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
