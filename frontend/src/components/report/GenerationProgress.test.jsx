import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { GenerationProgress } from "@/components/report/GenerationProgress";
import { renderWithProviders } from "@/test/utils";

/**
 * The live section list.
 *
 * The retry row is the reason this screen exists — a section failing
 * validation and recovering on the repair prompt is the system demonstrating
 * its own robustness, and behind a spinner nobody ever sees it. So the test
 * that matters here is that `retrying` renders differently from both
 * `started` and `failed`, and says why the first attempt was rejected.
 */
const sections = [
  { name: "attack_types", state: "retrying", attempt: 2, reason: "parse: no JSON object found" },
  { name: "general_risk_assessment", state: "completed", items: 4, ungrounded: 1 },
  {
    name: "vulnerabilities",
    state: "failed",
    error: { section: "vulnerabilities", stage: "validation", detail: "cve_id: wrong type" },
  },
  { name: "anomalies", state: "started" },
  { name: "timeline", state: "pending" },
];

describe("GenerationProgress", () => {
  it("shows a retrying section with the reason its first attempt was rejected", () => {
    renderWithProviders(<GenerationProgress name="Test" sections={sections} />);

    expect(screen.getByText("Retrying — repair prompt")).toBeInTheDocument();
    expect(screen.getByText(/no JSON object found/)).toBeInTheDocument();
  });

  it("distinguishes all five section states", () => {
    renderWithProviders(<GenerationProgress name="Test" sections={sections} />);

    for (const label of ["Queued", "Analysing", "Retrying — repair prompt", "Complete", "Failed"]) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
  });

  it("renders a failed section's typed error, stage included", () => {
    renderWithProviders(<GenerationProgress name="Test" sections={sections} />);

    // The stage is what separates a provider outage from a model that will
    // not produce valid JSON, so it is never flattened into the message.
    expect(screen.getByText("(validation)")).toBeInTheDocument();
    expect(screen.getByText(/cve_id: wrong type/)).toBeInTheDocument();
  });

  it("surfaces ungrounded findings on a completed section", () => {
    renderWithProviders(<GenerationProgress name="Test" sections={sections} />);
    expect(screen.getByText(/1 ungrounded/)).toBeInTheDocument();
  });

  it("says generation is still running when the stream drops", () => {
    renderWithProviders(
      <GenerationProgress name="Test" sections={sections} reconnecting />,
    );

    // A dropped stream is not a dropped generation, and the difference has to
    // be on screen or the user restarts a report that is already running.
    expect(screen.getByText(/still running on the server/)).toBeInTheDocument();
    expect(screen.getByText(/nothing has been restarted/)).toBeInTheDocument();
    expect(screen.queryByText("Retrying — repair prompt")).not.toBeInTheDocument();
  });
});
