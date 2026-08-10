import { QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import MockAdapter from "axios-mock-adapter";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { AuthProvider, useAuth } from "@/context/AuthContext";
import { apiClient } from "@/lib/apiClient";
import { UNAUTHORIZED_EVENT, getToken, setToken } from "@/lib/token";
import { createTestQueryClient } from "@/test/utils";

/**
 * The frontend's answer to `get_current_user`: the one place a component
 * learns who is calling. Everything here is about the boundary between the
 * token in storage and the user in memory — the two go out of step in exactly
 * three ways, and each one is a test.
 */
const ANALYST = { user_id: "u1", email: "analyst@aipcc.io", role: "analyst" };

function Probe() {
  const auth = useAuth();
  return (
    <div>
      <span data-testid="state">
        {auth.isResolving ? "resolving" : auth.isAuthenticated ? "in" : "out"}
      </span>
      <span data-testid="email">{auth.user?.email ?? "-"}</span>
      <span data-testid="admin">{String(auth.isAdmin)}</span>
      <button onClick={() => auth.login({ email: "a@b.io", password: "x" })}>sign in</button>
      <button onClick={auth.logout}>sign out</button>
    </div>
  );
}

function renderAuth() {
  const queryClient = createTestQueryClient();
  const result = render(
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <Probe />
      </AuthProvider>
    </QueryClientProvider>,
  );
  return { ...result, queryClient };
}

describe("AuthContext", () => {
  let mock;

  beforeEach(() => {
    mock = new MockAdapter(apiClient);
  });

  afterEach(() => {
    mock.restore();
  });

  it("is signed out, not resolving, when there is no token", () => {
    renderAuth();
    // The disabled `me` query stays pending forever. Reading `isPending`
    // without the token check would leave the login page on a splash screen.
    expect(screen.getByTestId("state")).toHaveTextContent("out");
  });

  it("stores the token and resolves the user on login", async () => {
    mock.onPost("/auth/login").reply(200, { access_token: "fresh-token" });
    mock.onGet("/auth/me").reply(200, ANALYST);

    renderAuth();
    await act(async () => {
      screen.getByText("sign in").click();
    });

    await waitFor(() => expect(screen.getByTestId("state")).toHaveTextContent("in"));
    expect(getToken()).toBe("fresh-token");
    expect(screen.getByTestId("email")).toHaveTextContent("analyst@aipcc.io");
    expect(screen.getByTestId("admin")).toHaveTextContent("false");
  });

  it("recognises an admin by role, case-insensitively", async () => {
    setToken("stored");
    mock.onGet("/auth/me").reply(200, { ...ANALYST, role: "Admin" });

    renderAuth();

    await waitFor(() => expect(screen.getByTestId("admin")).toHaveTextContent("true"));
  });

  it("clears the token and the previous user's data on logout", async () => {
    setToken("stored");
    mock.onGet("/auth/me").reply(200, ANALYST);

    const { queryClient } = renderAuth();
    await waitFor(() => expect(screen.getByTestId("state")).toHaveTextContent("in"));

    queryClient.setQueryData(["reports"], [{ report_name: "the last user's report" }]);

    await act(async () => {
      screen.getByText("sign out").click();
    });

    expect(getToken()).toBeNull();
    expect(screen.getByTestId("state")).toHaveTextContent("out");
    // The next user must not see the last one's reports sitting in the cache
    // while their own request is in flight. Asserted on a real cache entry
    // rather than on an empty cache: the provider immediately re-registers its
    // own (disabled) `me` query, so "nothing at all" is never true.
    expect(queryClient.getQueryData(["reports"])).toBeUndefined();
  });

  it("signs out when apiClient announces a dead session", async () => {
    setToken("stored");
    mock.onGet("/auth/me").reply(200, ANALYST);

    renderAuth();
    await waitFor(() => expect(screen.getByTestId("state")).toHaveTextContent("in"));

    // What the 401 interceptor dispatches from anywhere in the app.
    await act(async () => {
      window.dispatchEvent(new CustomEvent(UNAUTHORIZED_EVENT));
    });

    expect(screen.getByTestId("state")).toHaveTextContent("out");
  });

  it("is signed out when a token exists but the user cannot be fetched", async () => {
    setToken("stale");
    mock.onGet("/auth/me").reply(401, { detail: "user no longer exists" });

    renderAuth();

    await waitFor(() => expect(screen.getByTestId("state")).toHaveTextContent("out"));
  });

  it("refuses to be used outside a provider", () => {
    // Otherwise a component rendered in the wrong tree reads `null` and fails
    // later with "cannot read property of null" somewhere unrelated.
    expect(() => render(<Probe />)).toThrow(/useAuth must be used inside/);
  });
});
