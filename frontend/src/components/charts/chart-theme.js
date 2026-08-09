/**
 * Shared chart styling.
 *
 * The design system's one rule applies to charts as much as to badges: colour
 * encodes severity or state, nothing else. So the frequency and volume charts
 * are drawn in graphite — a bar being taller already says "more", and spending
 * a hue on it would make the coloured things mean less. Only the severity
 * chart and the "needs attention" series carry chroma, because in both cases
 * the colour *is* the information.
 *
 * Colours are `var(--color-*)` rather than hex literals so `index.css` stays
 * the single source of the palette. SVG presentation attributes resolve CSS
 * custom properties, so Recharts passes these straight through.
 */

export const INK = "var(--color-ink)";
export const INK_DIM = "var(--color-ink-dim)";
export const INK_FAINT = "var(--color-ink-faint)";
export const LINE = "var(--color-line)";

/** Matches `SEVERITY_TOKENS` in `lib/format.js`, and the server's ladder. */
export const SEVERITY_COLOR = {
  critical: "var(--color-critical)",
  high: "var(--color-high)",
  medium: "var(--color-medium)",
  low: "var(--color-low)",
  unknown: "var(--color-info)",
};

export const SEVERITY_LABEL = {
  critical: "Critical",
  high: "High",
  medium: "Medium",
  low: "Low",
  unknown: "Unrated",
};

export const AXIS = {
  tickLine: false,
  axisLine: false,
  tick: { fill: INK_FAINT, fontSize: 11, fontFamily: "var(--font-mono)" },
};

export const GRID = {
  stroke: LINE,
  strokeDasharray: "2 4",
  vertical: false,
};

/** The hover cursor is a wash, never a coloured highlight. */
export const CURSOR_FILL = { fill: "var(--color-raised)", fillOpacity: 0.6 };
export const CURSOR_LINE = { stroke: "var(--color-line-strong)", strokeWidth: 1 };

const DAY_LABEL = new Intl.DateTimeFormat(undefined, { month: "short", day: "2-digit" });

/**
 * Format a `YYYY-MM-DD` bucket for an axis.
 *
 * Parsed field by field rather than through `new Date(string)`: the ISO date
 * form is parsed as UTC midnight, so west of Greenwich it renders as the
 * previous day and every bucket on the chart is labelled one day early.
 */
export function formatDay(value) {
  if (typeof value !== "string") return String(value ?? "");
  const [year, month, day] = value.split("-").map(Number);
  if (!year || !month || !day) return value;
  return DAY_LABEL.format(new Date(year, month - 1, day));
}

export function formatCount(value) {
  const number = Number(value) || 0;
  if (number >= 1_000_000) return `${(number / 1_000_000).toFixed(1)}M`;
  if (number >= 1_000) return `${(number / 1_000).toFixed(number >= 10_000 ? 0 : 1)}k`;
  return String(number);
}
