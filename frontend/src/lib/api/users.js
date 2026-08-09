import { apiClient } from "@/lib/apiClient";

export async function list() {
  const { data } = await apiClient.get("/users");
  return data;
}

export async function get(userId) {
  const { data } = await apiClient.get(`/users/${userId}`);
  return data;
}

/** Admin-only. Unlike `/auth/register`, this path may set a role. */
export async function create(payload) {
  const { data } = await apiClient.post("/users", payload);
  return data;
}

export async function setRole(userId, role) {
  const { data } = await apiClient.patch(`/users/${userId}/role`, { role });
  return data;
}

export async function setStatus(userId, status) {
  const { data } = await apiClient.patch(`/users/${userId}/status`, { status });
  return data;
}

export async function remove(userId) {
  await apiClient.delete(`/users/${userId}`);
}
