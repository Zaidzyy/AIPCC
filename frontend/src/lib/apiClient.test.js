import MockAdapter from "axios-mock-adapter";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { apiClient, errorDetail, errorMessage } from "@/lib/apiClient";
import { UNAUTHORIZED_EVENT, getToken, setToken } from "@/lib/token";

/**
 * The 401 interceptor is the single most load-bearing twelve lines in the
 * frontend: it is what turns an expired token into a redirect instead of a
 * screen of failed requests, and it is invisible when it works. It also has a
 * carve-out — a 401 from `/auth/login` is a wrong password, not a dead session
 * — and getting that backwards makes a typo log you out of a session you
 * never had.
 */
describe("apiClient 401 interceptor", () => {
  let mock;
  let unauthorized;

  beforeEach(() => {
    mock = new MockAdapter(apiClient);
    unauthorized = vi.fn();
    window.addEventListener(UNAUTHORIZED_EVENT, unauthorized);
    setToken("a-stored-token");
  });

  afterEach(() => {
    mock.restore();
    window.removeEventListener(UNAUTHORIZED_EVENT, unauthorized);
  });

  it("attaches the stored token to every request", async () => {
    mock.onGet("/reports").reply(200, []);
    await apiClient.get("/reports");
    expect(mock.history.get[0].headers.Authorization).toBe("Bearer a-stored-token");
  });

  it("sends no Authorization header when there is no token", async () => {
    setToken(null);
    mock.onGet("/share/shr_x_y").reply(200, {});
    await apiClient.get("/share/shr_x_y");
    expect(mock.history.get[0].headers.Authorization).toBeUndefined();
  });

  it("clears the token and announces a dead session on a 401", async () => {
    mock.onGet("/reports").reply(401, { detail: "token expired" });

    await expect(apiClient.get("/reports")).rejects.toThrow();

    expect(getToken()).toBeNull();
    expect(unauthorized).toHaveBeenCalledTimes(1);
  });

  it("leaves the session alone when the 401 came from login", async () => {
    mock.onPost("/auth/login").reply(401, { detail: "incorrect email or password" });

    await expect(apiClient.post("/auth/login")).rejects.toThrow();

    expect(getToken()).toBe("a-stored-token");
    expect(unauthorized).not.toHaveBeenCalled();
  });

  it("leaves the session alone on any other failure", async () => {
    mock.onGet("/reports").reply(500);
    await expect(apiClient.get("/reports")).rejects.toThrow();

    mock.onGet("/reports/x").reply(403);
    await expect(apiClient.get("/reports/x")).rejects.toThrow();

    expect(getToken()).toBe("a-stored-token");
    expect(unauthorized).not.toHaveBeenCalled();
  });
});

/**
 * FastAPI answers with `detail` in three different shapes and all three reach
 * the UI. Rendering an object into JSX throws, so this is the difference
 * between an error message and a white screen.
 */
describe("errorMessage", () => {
  const wrap = (data, status = 400) => ({ response: { status, data } });

  it("reads a plain HTTPException detail", () => {
    expect(errorMessage(wrap({ detail: "report not found" }))).toBe("report not found");
  });

  it("reads a request-validation array and names the field", () => {
    const error = wrap({
      detail: [{ loc: ["body", "classification"], msg: "Input should be 'Public'" }],
    });
    expect(errorMessage(error)).toBe("classification: Input should be 'Public'");
  });

  it("reads the structured 502 that report generation raises", () => {
    const error = wrap({ detail: { message: "no usable sections", errors: [] } }, 502);
    expect(errorMessage(error)).toBe("no usable sections");
    expect(errorDetail(error)).toEqual({ message: "no usable sections", errors: [] });
  });

  it("names the API when the backend is unreachable", () => {
    expect(errorMessage({ code: "ERR_NETWORK" })).toMatch(/Is the backend running/);
  });

  it("falls back rather than rendering undefined", () => {
    expect(errorMessage(null)).toBe("Something went wrong.");
    expect(errorMessage(wrap({ detail: [] }))).toBe("Something went wrong.");
  });

  it("does not mistake an array detail for a structured one", () => {
    expect(errorDetail(wrap({ detail: [{ msg: "x" }] }))).toBeNull();
  });
});
