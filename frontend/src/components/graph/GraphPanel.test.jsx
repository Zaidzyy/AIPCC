import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import MockAdapter from "axios-mock-adapter";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { GraphPanel } from "@/components/graph/GraphPanel";
import { apiClient } from "@/lib/apiClient";
import { renderWithProviders } from "@/test/utils";

/**
 * The graph panel, tested on its two honesty requirements.
 *
 * A report with no entity data must say so rather than render an empty canvas,
 * and a graph that had to drop nodes to stay readable must admit it — a
 * picture that silently omits half a report is worse than no picture.
 *
 * The force layout itself is not tested. Asserting on coordinates produced by
 * a physics simulation is a test that fails when d3 changes a constant and
 * passes when the graph is unreadable, which is the wrong way round.
 */
const REPORT_ID = "11111111-1111-4111-8111-111111111111";

const node = (overrides) => ({
  id: "10.0.0.1",
  label: "10.0.0.1",
  type: "host",
  aliases: [],
  risk: "unknown",
  degree: 1,
  observations: 1,
  findings: [],
  ...overrides,
});

function respond(mock, graph) {
  mock.onGet(`/reports/${REPORT_ID}/graph`).reply(200, {
    report_id: REPORT_ID,
    nodes: [],
    edges: [],
    total_nodes: 0,
    total_edges: 0,
    truncated: false,
    empty_reason: null,
    ...graph,
  });
}

describe("GraphPanel", () => {
  let mock;

  beforeEach(() => {
    mock = new MockAdapter(apiClient);
  });

  afterEach(() => {
    mock.restore();
  });

  it("says a report has no entities rather than drawing an empty canvas", async () => {
    respond(mock, {
      empty_reason: "This report records no entities. Its anomalies and timeline carry none.",
    });
    renderWithProviders(<GraphPanel reportId={REPORT_ID} />);

    expect(await screen.findByText("No entities to graph")).toBeInTheDocument();
    expect(screen.getByText(/records no entities/)).toBeInTheDocument();
  });

  it("distinguishes a failure from an empty graph", async () => {
    mock.onGet(`/reports/${REPORT_ID}/graph`).reply(500);
    renderWithProviders(<GraphPanel reportId={REPORT_ID} />);

    await waitFor(() =>
      expect(screen.getByText("Could not build the graph")).toBeInTheDocument(),
    );
    expect(screen.queryByText("No entities to graph")).not.toBeInTheDocument();
  });

  it("admits when it had to drop nodes to stay readable", async () => {
    respond(mock, {
      nodes: [node()],
      total_nodes: 140,
      truncated: true,
    });
    renderWithProviders(<GraphPanel reportId={REPORT_ID} />);

    expect(
      await screen.findByText(/Showing the 1 highest-risk of 140/),
    ).toBeInTheDocument();
  });

  it("shows the findings behind a node, each with the basis of its link", async () => {
    respond(mock, {
      nodes: [
        node({
          risk: "critical",
          aliases: ["4471"],
          findings: [
            { section: "attack_types", title: "Ransomware", risk_level: "Critical", basis: "evidence" },
            { section: "anomalies", title: "Burst", basis: "source" },
          ],
        }),
      ],
      total_nodes: 1,
    });
    const { container } = renderWithProviders(<GraphPanel reportId={REPORT_ID} />);

    // Wait for the lazy chunk, not for any <svg> — the card header carries a
    // lucide icon and would match first.
    await waitFor(() =>
      expect(container.querySelector('g[role="button"]')).toBeInTheDocument(),
    );
    await userEvent.click(container.querySelector('g[role="button"]'));

    expect(screen.getByText("Ransomware")).toBeInTheDocument();
    // The basis is never hidden: "cites the same log lines" and "the model
    // wrote this name in its description" are different strengths of claim.
    expect(screen.getByText("evidence")).toBeInTheDocument();
    expect(screen.getByText("source")).toBeInTheDocument();
    // And a merge is shown as the claim it is.
    expect(screen.getByText(/merged because a single log row named both/)).toBeInTheDocument();
  });
});
