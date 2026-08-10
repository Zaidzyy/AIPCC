import { apiClient } from "@/lib/apiClient";

/**
 * Dashboard aggregates.
 *
 * Every one of these is computed by a `GROUP BY` in Postgres and scoped to the
 * caller — an analyst's numbers cover their own reports, an admin's cover all
 * of them. Nothing here is counted in the browser.
 */

export async function summary() {
  const { data } = await apiClient.get("/dashboard/summary");
  return data;
}

export async function reportsOverTime(days = 30) {
  const { data } = await apiClient.get("/dashboard/reports-over-time", { params: { days } });
  return data;
}

export async function severity() {
  const { data } = await apiClient.get("/dashboard/severity");
  return data;
}

export async function topAttackTypes(limit = 8) {
  const { data } = await apiClient.get("/dashboard/top-attack-types", { params: { limit } });
  return data;
}

export async function anomaliesOverTime(days = 30) {
  const { data } = await apiClient.get("/dashboard/anomalies-over-time", { params: { days } });
  return data;
}

/**
 * Cost accounting (Phase 9).
 *
 * Every money and token field in these responses can be `null`, and `null`
 * means "not measured" — a provider that reported no usage, or a model with no
 * configured price. It never means zero. See `services/llm/pricing.py`; the
 * formatters in `lib/format.js` render it as `—`.
 */

export async function usageSummary() {
  const { data } = await apiClient.get("/dashboard/usage-summary");
  return data;
}

export async function costOverTime(days = 30) {
  const { data } = await apiClient.get("/dashboard/cost-over-time", { params: { days } });
  return data;
}

export async function tokensBySection() {
  const { data } = await apiClient.get("/dashboard/tokens-by-section");
  return data;
}

export async function generationLatency(days = 30) {
  const { data } = await apiClient.get("/dashboard/generation-latency", { params: { days } });
  return data;
}
