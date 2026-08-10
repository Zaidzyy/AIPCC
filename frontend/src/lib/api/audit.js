import { apiClient } from "@/lib/apiClient";

/**
 * The audit trail. Admin-only, and read-only by design — there is deliberately
 * no create, update or delete here, because the table is append-only and the
 * client must not be the thing that suggests otherwise. See
 * `backend/app/api/routers/audit.py`.
 */

export async function list(params = {}) {
  const { data } = await apiClient.get("/audit", { params });
  return data;
}

export async function filters() {
  const { data } = await apiClient.get("/audit/filters");
  return data;
}
