import { describe, expect, it } from "vitest";

import { groupEvidence } from "@/lib/evidence";

/**
 * The distinction this file exists to protect: `null` and `[]` mean different
 * things, and collapsing them breaks the feature in opposite directions.
 *
 * `null` — this view has no evidence at all (the public share view), so no
 * disclosure should render and nothing should be labelled ungrounded.
 * `[]` — this finding has no valid citation, which is a real finding about the
 * model and must be shown.
 */
const ROW = (item_id, evidence_id) => ({
  evidence_id,
  item_id,
  section: "attack_types",
  chunk_id: 3,
  excerpt: "10.0.0.1 failed_login",
  row_start: 4,
  row_end: 6,
});

describe("groupEvidence", () => {
  it("returns null when the report carries no evidence array", () => {
    // The shared-report response. A share link grants read of a report; the
    // raw log excerpts behind it are deliberately not part of that.
    expect(groupEvidence({ sections: {} })).toBeNull();
    expect(groupEvidence(undefined)).toBeNull();
  });

  it("returns an empty map — not null — when the array is present but empty", () => {
    const grouped = groupEvidence({ evidence: [] });
    expect(grouped).not.toBeNull();
    expect(grouped.size).toBe(0);
    // Which is what makes every finding read as ungrounded rather than as
    // "this view does not show sources".
    expect(grouped.get("any-item") ?? []).toEqual([]);
  });

  it("groups several citations under one finding", () => {
    const grouped = groupEvidence({
      evidence: [ROW("item-a", "e1"), ROW("item-b", "e2"), ROW("item-a", "e3")],
    });

    expect(grouped.get("item-a")).toHaveLength(2);
    expect(grouped.get("item-b")).toHaveLength(1);
    expect(grouped.get("item-c")).toBeUndefined();
  });
});
