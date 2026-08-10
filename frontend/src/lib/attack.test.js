import { describe, expect, it } from "vitest";

import { foldDetections } from "./attack";

/**
 * The one rule in the matrix's client-side layer worth pinning down.
 *
 * Sub-techniques do not get cells, so a detection on `T1059.001` has to shade
 * the `T1059` cell. Get that wrong and a report whose findings are all
 * sub-techniques renders an empty matrix — which looks exactly like a report
 * that found nothing, and is the failure this project keeps naming: an absent
 * thing and a failed thing must never look alike.
 */
const detection = (overrides) => ({
  technique_id: "T1059",
  name: "Command and Scripting Interpreter",
  parent_id: "T1059",
  sub_technique: false,
  count: 1,
  verified: true,
  issue: null,
  tactics: ["execution"],
  sources: [],
  ...overrides,
});

describe("foldDetections", () => {
  it("rolls a sub-technique onto its parent cell", () => {
    const folded = foldDetections([
      detection({ technique_id: "T1059.001", parent_id: "T1059", sub_technique: true, count: 3 }),
    ]);

    expect([...folded.keys()]).toEqual(["T1059"]);
    const cell = folded.get("T1059");
    expect(cell.total).toBe(3);
    expect(cell.direct).toBe(0);
    expect(cell.viaSubs).toBe(3);
    expect(cell.subs).toHaveLength(1);
  });

  it("sums a parent and its children into one total", () => {
    const folded = foldDetections([
      detection({ count: 2 }),
      detection({ technique_id: "T1059.003", parent_id: "T1059", sub_technique: true, count: 5 }),
    ]);

    const cell = folded.get("T1059");
    expect(cell.total).toBe(7);
    expect(cell.detections).toHaveLength(2);
  });

  it("marks the cell unverified when any detection under it is", () => {
    const folded = foldDetections([
      detection({ count: 9 }),
      detection({
        technique_id: "T1059.001",
        parent_id: "T1059",
        sub_technique: true,
        verified: false,
        issue: "T1059.001 is 'PowerShell', not 'PS Remoting'",
      }),
    ]);

    // One bad child is enough. Requiring *every* detection to be unverified
    // would hide exactly the case worth surfacing.
    expect(folded.get("T1059").unverified).toBe(true);
  });

  it("keeps distinct parents apart", () => {
    const folded = foldDetections([
      detection(),
      detection({ technique_id: "T1110", parent_id: "T1110", name: "Brute Force", count: 4 }),
    ]);

    expect(folded.get("T1110").total).toBe(4);
    expect(folded.get("T1059").total).toBe(1);
  });

  it("returns an empty map for no detections", () => {
    expect(foldDetections().size).toBe(0);
    expect(foldDetections([]).size).toBe(0);
  });
});
