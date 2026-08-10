import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import MockAdapter from "axios-mock-adapter";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import { AuthProvider } from "@/context/AuthContext";
import { apiClient } from "@/lib/apiClient";
import { setToken } from "@/lib/token";
import { AdminRoute, ProtectedRoute } from "@/routes/ProtectedRoute";
import { createTestQueryClient } from "@/test/utils";

/**
 * The gate on every authenticated route.
 *
 * The failure mode worth guarding is not "an anonymous visitor sees the
 * dashboard" — that one is obvious the first time anybody tries it. It is the
 * refresh bounce: a stored token is still being exchanged for a user, the
 * gate reads `isAuthenticated` as false for one render, and every reload
 * throws the user out to /login and back. So the third state — resolving —
 * gets a test of its own.
 */
const ANALYST = { user_id: "u1", email: "analyst@aipcc.io", role: "analyst" };
const ADMIN = { ...ANALYST, role: "admin" };

function renderRoutes(Gate = ProtectedRoute) {
  const queryClient = createTestQueryClient();
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={["/reports"]}>
        <AuthProvider>
          <Routes>
            <Route path="/login" element={<p>Login page</p>} />
            <Route path="/dashboard" element={<p>Dashboard page</p>} />
            <Route element={<Gate />}>
              <Route path="/reports" element={<p>Reports page</p>} />
            </Route>
          </Routes>
        </AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("ProtectedRoute", () => {
  let mock;

  beforeEach(() => {
    mock = new MockAdapter(apiClient);
  });

  afterEach(() => {
    mock.restore();
  });

  it("redirects to login when there is no token", () => {
    renderRoutes();
    expect(screen.getByText("Login page")).toBeInTheDocument();
    expect(screen.queryByText("Reports page")).not.toBeInTheDocument();
  });

  it("holds rather than redirecting while a stored token is being resolved", () => {
    setToken("stored-token");
    // Never resolves during this assertion — the request is still in flight,
    // which is exactly the render the refresh bounce happens on.
    mock.onGet("/auth/me").reply(() => new Promise(() => {}));

    renderRoutes();

    expect(screen.getByRole("status")).toHaveTextContent(/restoring session/i);
    expect(screen.queryByText("Login page")).not.toBeInTheDocument();
  });

  it("renders the route once the token resolves to a user", async () => {
    setToken("stored-token");
    mock.onGet("/auth/me").reply(200, ANALYST);

    renderRoutes();

    expect(await screen.findByText("Reports page")).toBeInTheDocument();
  });

  it("redirects when a stored token no longer resolves to a user", async () => {
    setToken("stale-token");
    mock.onGet("/auth/me").reply(401, { detail: "user no longer exists" });

    renderRoutes();

    expect(await screen.findByText("Login page")).toBeInTheDocument();
  });
});

describe("AdminRoute", () => {
  let mock;

  beforeEach(() => {
    mock = new MockAdapter(apiClient);
    setToken("stored-token");
  });

  afterEach(() => {
    mock.restore();
  });

  it("lets an admin through", async () => {
    mock.onGet("/auth/me").reply(200, ADMIN);
    renderRoutes(AdminRoute);
    expect(await screen.findByText("Reports page")).toBeInTheDocument();
  });

  it("sends an analyst to the dashboard, not to login", async () => {
    mock.onGet("/auth/me").reply(200, ANALYST);
    renderRoutes(AdminRoute);
    // Being signed in and lacking a role is not the same as being signed out.
    expect(await screen.findByText("Dashboard page")).toBeInTheDocument();
  });
});
