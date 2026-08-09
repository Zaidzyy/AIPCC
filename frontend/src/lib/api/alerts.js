import { apiClient } from "@/lib/apiClient";

/**
 * Security alerts.
 *
 * Raised by the n8n FIM engine when a report's source document stops matching
 * the hash it was sealed with, and by the orchestrator when threat intel
 * pushes a report over its alerting threshold.
 */

export async function list(status) {
  const { data } = await apiClient.get("/alerts", {
    params: status ? { status } : undefined,
  });
  return data;
}

export async function setStatus(alertId, status) {
  const { data } = await apiClient.patch(`/alerts/${alertId}`, { status });
  return data;
}

export async function remove(alertId) {
  await apiClient.delete(`/alerts/${alertId}`);
}
