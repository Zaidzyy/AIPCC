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
