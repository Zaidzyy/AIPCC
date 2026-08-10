import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import MockAdapter from "axios-mock-adapter";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { apiClient } from "@/lib/apiClient";
import { Reports } from "@/pages/Reports";
import { renderWithProviders } from "@/test/utils";

/**
 * One data-driven page, tested through its four states.
 *
 * "Empty is not the same as failed" is a rule this app states out loud, and
 * it is the kind of rule that erodes silently: a refactor that collapses the
 * error branch into the empty branch breaks nothing visible in development,
 * where the API is always up. So loading, empty, error and
 * filtered-to-nothing are each asserted to render something different.
 */
const REPORTS = [
  {
    report_id: "11111111-1111-4111-8111-111111111111",
    report_name: "Weekly threat summary",
    document_id: "d1",
    user_id: "u1",
    classification: "Internal",
    status: "complete",
    generated_at: "2026-08-01T09:00:00Z",
    integrity_state: "SEALED",
  },
  {
    report_id: "22222222-2222-4222-8222-222222222222",
    report_name: "Credential exposure review",
    document_id: "d2",
    user_id: "u1",
    classification: "Confidential",
    status: "partial",
    generated_at: "2026-08-02T09:00:00Z",
    integrity_state: "UNKNOWN",
  },
];

describe("Reports page", () => {
  let mock;

  beforeEach(() => {
    mock = new MockAdapter(apiClient);
  });

  afterEach(() => {
    mock.restore();
  });

  it("shows a skeleton while loading, not an empty state", () => {
    mock.onGet("/reports").reply(() => new Promise(() => {}));

    const { container } = renderWithProviders(<Reports />);

    expect(screen.queryByText("No reports yet")).not.toBeInTheDocument();
    expect(screen.queryByText("Could not load reports")).not.toBeInTheDocument();
    expect(container.querySelectorAll(".animate-shimmer, [data-slot='skeleton']").length)
      .toBeGreaterThan(0);
  });

  it("distinguishes 'there are none' from 'I could not read this'", async () => {
    mock.onGet("/reports").reply(200, []);
    renderWithProviders(<Reports />);

    expect(await screen.findByText("No reports yet")).toBeInTheDocument();
    expect(screen.queryByText(/could not load/i)).not.toBeInTheDocument();
  });

  it("renders the API error rather than an empty table", async () => {
    mock.onGet("/reports").reply(500, { detail: "database is unreachable" });
    renderWithProviders(<Reports />);

    expect(await screen.findByText("Could not load reports")).toBeInTheDocument();
    expect(screen.getByText(/database is unreachable/)).toBeInTheDocument();
    expect(screen.queryByText("No reports yet")).not.toBeInTheDocument();
  });

  it("lists reports with their status and classification", async () => {
    mock.onGet("/reports").reply(200, REPORTS);
    renderWithProviders(<Reports />);

    expect(await screen.findByText("Weekly threat summary")).toBeInTheDocument();
    expect(screen.getByText("Credential exposure review")).toBeInTheDocument();
    expect(screen.getByText("Confidential")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Weekly threat summary" })).toHaveAttribute(
      "href",
      `/reports/${REPORTS[0].report_id}`,
    );
  });

  it("says 'no matches' when a filter empties a non-empty list", async () => {
    mock.onGet("/reports").reply(200, REPORTS);
    renderWithProviders(<Reports />);

    await screen.findByText("Weekly threat summary");
    await userEvent.type(screen.getByLabelText("Filter reports"), "nothing matches this");

    // Filtered-to-nothing offers "clear filters"; genuinely-empty offers
    // "generate a report". Collapsing the two would tell a user with reports
    // that they have none.
    expect(await screen.findByText("No matches")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /clear filters/i })).toBeInTheDocument();
    expect(screen.queryByText("No reports yet")).not.toBeInTheDocument();
  });

  it("filters by name and by the short id shown in the table", async () => {
    mock.onGet("/reports").reply(200, REPORTS);
    renderWithProviders(<Reports />);
    await screen.findByText("Weekly threat summary");

    const filter = screen.getByLabelText("Filter reports");

    await userEvent.type(filter, "credential");
    await waitFor(() =>
      expect(screen.queryByText("Weekly threat summary")).not.toBeInTheDocument(),
    );
    expect(screen.getByText("Credential exposure review")).toBeInTheDocument();

    await userEvent.clear(filter);
    await userEvent.type(filter, "11111111");
    expect(await screen.findByText("Weekly threat summary")).toBeInTheDocument();
    expect(screen.queryByText("Credential exposure review")).not.toBeInTheDocument();
  });
});
