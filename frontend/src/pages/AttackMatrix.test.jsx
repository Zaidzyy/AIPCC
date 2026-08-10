import { screen, waitFor } from "@testing-library/react";
import MockAdapter from "axios-mock-adapter";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { apiClient } from "@/lib/apiClient";
import { AttackMatrix } from "@/pages/AttackMatrix";
import { renderWithProviders } from "@/test/utils";

/**
 * The matrix page, tested on the two things that are easy to get quietly wrong.
 *
 * A report that found nothing must not render as a grid of empty cells, and an
 * identifier the model invented must not vanish. The second is the whole
 * argument of the phase: dropping an unplaceable technique would make this
 * page look cleaner than the output behind it.
 */
const GRID = {
  attack_version: "17.1",
  technique_count: 2,
  tactics: [
    {
      tactic_id: "TA0002",
      shortname: "execution",
      name: "Execution",
      description: "Running attacker code.",
      techniques: [
        {
          technique_id: "T1059",
          name: "Command and Scripting Interpreter",
          sub_technique: false,
          sub_techniques: [
            { technique_id: "T1059.001", name: "PowerShell", sub_technique: true, sub_techniques: [] },
          ],
        },
      ],
    },
    {
      tactic_id: "TA0010",
      shortname: "exfiltration",
      name: "Exfiltration",
      description: "Getting data out.",
      techniques: [
        {
          technique_id: "T1041",
          name: "Exfiltration Over C2 Channel",
          sub_technique: false,
          sub_techniques: [],
        },
      ],
    },
  ],
};

const detection = (overrides) => ({
  technique_id: "T1059",
  name: "Command and Scripting Interpreter",
  parent_id: "T1059",
  sub_technique: false,
  tactics: ["execution"],
  count: 2,
  verified: true,
  issue: null,
  sources: [],
  ...overrides,
});

function respond(mock, { detections = [], unplaced = [], emitted = null } = {}) {
  mock.onGet("/attack/matrix").reply(200, GRID);
  mock.onGet("/reports").reply(200, []);
  mock.onGet("/attack/detections").reply(200, {
    attack_version: "17.1",
    scope: "all",
    report_id: null,
    detections,
    unplaced,
    reports_considered: 3,
    techniques_emitted:
      emitted ??
      detections.reduce((sum, item) => sum + item.count, 0) +
        unplaced.reduce((sum, item) => sum + item.count, 0),
  });
}

describe("ATT&CK matrix page", () => {
  let mock;

  beforeEach(() => {
    mock = new MockAdapter(apiClient);
  });

  afterEach(() => {
    mock.restore();
  });

  it("renders every tactic column, including the ones with nothing in them", async () => {
    respond(mock, { detections: [detection()] });
    renderWithProviders(<AttackMatrix />);

    expect(await screen.findByText("Execution")).toBeInTheDocument();
    // The recognisable thing about this diagram is its shape, so a quiet
    // tactic keeps its column and says so rather than disappearing.
    expect(screen.getByText("Exfiltration")).toBeInTheDocument();
    expect(screen.getByText("No detections")).toBeInTheDocument();
  });

  it("shades a parent cell for a detection on its sub-technique", async () => {
    respond(mock, {
      detections: [
        detection({ technique_id: "T1059.001", sub_technique: true, name: "PowerShell", count: 4 }),
      ],
    });
    renderWithProviders(<AttackMatrix />);

    const cell = await screen.findByTitle(/T1059 · Command and Scripting Interpreter · 4/);
    expect(cell).toBeEnabled();
    expect(screen.getByText("1 sub-technique")).toBeInTheDocument();
  });

  it("lists an unplaceable identifier instead of dropping it", async () => {
    respond(mock, {
      detections: [detection()],
      unplaced: [
        {
          value: "T9999",
          reason: "mitre_unknown",
          detail: "T9999 does not exist in ATT&CK Enterprise (823 techniques)",
          count: 1,
          sources: [],
        },
      ],
    });
    renderWithProviders(<AttackMatrix />);

    expect(await screen.findByText("Reported, but not on the matrix")).toBeInTheDocument();
    expect(screen.getByText("T9999")).toBeInTheDocument();
    expect(screen.getByText(/does not exist in ATT&CK Enterprise/)).toBeInTheDocument();
  });

  it("says nothing was detected rather than drawing an empty grid", async () => {
    respond(mock, { detections: [], unplaced: [], emitted: 0 });
    renderWithProviders(<AttackMatrix />);

    expect(await screen.findByText("No techniques have been detected yet")).toBeInTheDocument();
    expect(screen.queryByText("Execution")).not.toBeInTheDocument();
  });

  it("distinguishes a failure from an empty result", async () => {
    mock.onGet("/attack/matrix").reply(200, GRID);
    mock.onGet("/reports").reply(200, []);
    mock.onGet("/attack/detections").reply(500);
    renderWithProviders(<AttackMatrix />);

    await waitFor(() =>
      expect(screen.getByText("Could not load the matrix")).toBeInTheDocument(),
    );
    expect(screen.queryByText("No techniques have been detected yet")).not.toBeInTheDocument();
  });
});
