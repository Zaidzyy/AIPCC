import { describe, expect, it } from "vitest";

import { formatDuration, formatTokens, formatUsd } from "@/lib/format";

/**
 * The null-is-not-zero rule, at the last place it can be broken.
 *
 * The backend is careful all the way down — `services/llm/pricing.py` returns
 * `None` rather than `0` for an unpriced model or an unreported token count —
 * and a single `?? 0` in a formatter would undo all of it and print `$0.00`
 * next to a report that definitely cost something. These are cheap tests for
 * an invariant that spans two languages and four layers.
 */
describe("formatUsd", () => {
  it("renders an unmeasured cost as a dash, never as zero", () => {
    expect(formatUsd(null)).toBe("—");
    expect(formatUsd(undefined)).toBe("—");
  });

  it("distinguishes a genuine zero from an unmeasured one", () => {
    // Ollama is free, and that is a real number. It must not look like "—".
    expect(formatUsd(0)).toBe("$0");
  });

  it("keeps enough precision to be useful at this scale", () => {
    // Two decimals would print $0.00 for every report and make the whole
    // feature look broken.
    expect(formatUsd(0.00042)).toBe("$0.0004");
    expect(formatUsd(0.123)).toBe("$0.123");
    expect(formatUsd(12.5)).toBe("$12.50");
  });
});

describe("formatDuration", () => {
  it("renders unmeasured time as a dash", () => {
    expect(formatDuration(null)).toBe("—");
  });

  it("scales to the largest sensible unit", () => {
    expect(formatDuration(450)).toBe("450ms");
    expect(formatDuration(2500)).toBe("2.5s");
    expect(formatDuration(125_000)).toBe("2m 5s");
  });
});

describe("formatTokens", () => {
  it("renders unmeasured tokens as a dash, not 0", () => {
    expect(formatTokens(null)).toBe("—");
    expect(formatTokens(0)).toBe("0");
  });

  it("abbreviates large counts", () => {
    expect(formatTokens(1500)).toBe("1.5k");
    expect(formatTokens(2_400_000)).toBe("2.4M");
  });
});
