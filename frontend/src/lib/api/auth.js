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
