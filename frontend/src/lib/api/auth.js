import { apiClient } from "@/lib/apiClient";

/**
 * OAuth2 password flow. The backend expects form encoding with `username`
 * holding the email — not JSON, and not a field called `email`.
 */
export async function login({ email, password }) {
  const form = new URLSearchParams();
  form.set("username", email);
  form.set("password", password);

  const { data } = await apiClient.post("/auth/login", form, {
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
  });
  return data;
}

export async function register(payload) {
  const { data } = await apiClient.post("/auth/register", payload);
  return data;
}

/**
 * Records the end of a session in the audit trail. It does **not** invalidate
 * the token — access tokens are stateless JWTs and stay valid until they
 * expire, whatever this call does. The client still clears its own copy; this
 * is purely so "signed out at 14:02" exists to compare against later activity.
 */
export async function logout() {
  await apiClient.post("/auth/logout");
}

export async function me() {
  const { data } = await apiClient.get("/auth/me");
  return data;
}

export async function changePassword({ currentPassword, newPassword }) {
  await apiClient.post("/auth/change-password", {
    current_password: currentPassword,
    new_password: newPassword,
  });
}
