/**
 * Display formatting.
 *
 * Severity lives here rather than in a component because it is the app's one
 * colour system — see the header of `index.css`. Every badge, rule and spine
 * resolves through `severityToken`, so the ramp is defined once.
 */

/** Ordered low → critical, matching the ladder the report prompts ask for. */
export const SEVERITIES = ["low", "medium", "high", "critical"];

/**
 * Every class name here is written out in full, never assembled at runtime.
 * Tailwind generates utilities by scanning source text: a class produced by
 * string concatenation or `.replace()` is invisible to that scan and silently
 * never gets a rule, which shows up as an element that quietly falls back to
 * the inherited colour.
 */
const SEVERITY_TOKENS = {
  critical: {
    key: "critical",
    label: "Critical",
    rank: 4,
    text: "text-critical",
    bg: "bg-critical",
    border: "border-critical/35",
    rule: "border-critical/60",
    tint: "bg-critical/10",
  },
  high: {
    key: "high",
    label: "High",
    rank: 3,
    text: "text-high",
    bg: "bg-high",
    border: "border-high/35",
    rule: "border-high/60",
    tint: "bg-high/10",
  },
  medium: {
    key: "medium",
    label: "Medium",
    rank: 2,
    text: "text-medium",
    bg: "bg-medium",
    border: "border-medium/35",
    rule: "border-medium/60",
    tint: "bg-medium/10",
  },
  low: {
    key: "low",
    label: "Low",
    rank: 1,
    text: "text-low",
    bg: "bg-low",
    border: "border-low/35",
    rule: "border-low/60",
    tint: "bg-low/10",
  },
  unknown: {
    key: "unknown",
    label: "Unrated",
    rank: 0,
    text: "text-info",
    bg: "bg-info",
    border: "border-info/30",
    rule: "border-line-strong",
    tint: "bg-info/10",
  },
};

/**
 * Resolve a severity string from the model into a token.
 *
 * The prompts ask for Low/Medium/High/Critical, but the field is nullable and
 * a model will still answer "Severe" or "Med" now and then. Anything
 * unrecognised resolves to `unknown` rather than rendering an uncoloured badge
 * that looks like a rendering bug.
 */
export function severityToken(value) {
  if (!value) return SEVERITY_TOKENS.unknown;
  const normalized = String(value).trim().toLowerCase();

  if (SEVERITY_TOKENS[normalized]) return SEVERITY_TOKENS[normalized];
  if (normalized.startsWith("crit") || normalized.startsWith("sev")) {
    return SEVERITY_TOKENS.critical;
  }
  if (normalized.startsWith("high")) return SEVERITY_TOKENS.high;
  if (normalized.startsWith("med") || normalized.startsWith("mod")) {
    return SEVERITY_TOKENS.medium;
  }
  if (normalized.startsWith("low") || normalized.startsWith("info")) {
    return SEVERITY_TOKENS.low;
  }
  return SEVERITY_TOKENS.unknown;
}

/** Count findings by severity, for the spine. */
export function severityCounts(items, field = "risk_level") {
  const counts = { critical: 0, high: 0, medium: 0, low: 0, unknown: 0 };
  for (const item of items ?? []) {
    counts[severityToken(item?.[field]).key] += 1;
  }
  return counts;
}

/** The most severe level present, or null when there is nothing to rate. */
export function peakSeverity(items, field = "risk_level") {
  let peak = null;
  for (const item of items ?? []) {
    const token = severityToken(item?.[field]);
    if (token.key === "unknown") continue;
    if (!peak || token.rank > peak.rank) peak = token;
  }
  return peak;
}

// --- Report status --------------------------------------------------------

const STATUS_TOKENS = {
  complete: { label: "Complete", text: "text-ok", dot: "bg-ok" },
  partial: { label: "Partial", text: "text-medium", dot: "bg-medium" },
  failed: { label: "Failed", text: "text-critical", dot: "bg-critical" },
  pending: { label: "Pending", text: "text-info", dot: "bg-info" },
};

export function statusToken(status) {
  const key = String(status ?? "").toLowerCase();
  return STATUS_TOKENS[key] ?? { label: status || "Unknown", text: "text-info", dot: "bg-info" };
}

// --- File integrity -------------------------------------------------------

/**
 * The FIM engine's verdict on a report's source document.
 *
 * UNKNOWN is grey on purpose. "Nobody has checked this" is not a mild version
 * of "this is fine" — it is the absence of a check — and colouring it green
 * would tell an analyst something no one has verified. Every class name is
 * written out in full; see the note on `SEVERITY_TOKENS`.
 */
const INTEGRITY_TOKENS = {
  SEALED: {
    key: "SEALED",
    label: "Sealed",
    description: "The source log still matches the hash recorded when this report was generated.",
    text: "text-ok",
    dot: "bg-ok",
    tint: "bg-ok/10",
    border: "border-ok/35",
  },
  TAMPERED: {
    key: "TAMPERED",
    label: "Tampered",
    description: "The source log no longer matches the hash recorded when this report was generated.",
    text: "text-critical",
    dot: "bg-critical",
    tint: "bg-critical/10",
    border: "border-critical/35",
  },
  UNKNOWN: {
    key: "UNKNOWN",
    label: "Unverified",
    description: "The integrity of the source log has not been checked yet.",
    text: "text-ink-dim",
    dot: "bg-ink-faint",
    tint: "bg-raised",
    border: "border-line-strong",
  },
};

export function integrityToken(state) {
  return INTEGRITY_TOKENS[String(state ?? "").toUpperCase()] ?? INTEGRITY_TOKENS.UNKNOWN;
}

// --- Audit ----------------------------------------------------------------

/**
 * The outcome of an audited action.
 *
 * Coloured, because an outcome is a state and states are the one thing chroma
 * is allowed to encode here. `blocked` is amber rather than red on purpose: a
 * refused login is the rate limiter working, which is not the same event as a
 * credential being guessed wrong, and painting them alike would hide a spray
 * inside a wall of red.
 *
 * Every class name is written out in full — see the note on `SEVERITY_TOKENS`.
 * A name assembled at runtime silently gets no rule, which cost this project a
 * whole set of severity borders once already.
 */
const OUTCOME_TOKENS = {
  success: { label: "Success", text: "text-ok", dot: "bg-ok" },
  failure: { label: "Failure", text: "text-critical", dot: "bg-critical" },
  blocked: { label: "Blocked", text: "text-medium", dot: "bg-medium" },
};

export function outcomeToken(outcome) {
  const key = String(outcome ?? "").toLowerCase();
  return OUTCOME_TOKENS[key] ?? { label: outcome || "Unknown", text: "text-ink-dim", dot: "bg-ink-faint" };
}

/**
 * `auth.login.failure` reads as "Login failure" in a table and as its raw id
 * in a filter. Both are wanted: the label is scannable, the id is what you
 * paste into a query or find in the backend source.
 */
export function actionLabel(action) {
  const parts = String(action ?? "").split(".");
  const verb = parts.slice(1).join(" ").replace(/_/g, " ");
  if (!verb) return action || "—";
  return (verb.charAt(0).toUpperCase() + verb.slice(1)).replace(/\bsuccess\b|\bfailure\b/, "").trim();
}

/** The `subject` half of a dotted action — `auth`, `user`, `report`, `share`. */
export function actionSubject(action) {
  return String(action ?? "").split(".")[0] || "—";
}

// --- Classification -------------------------------------------------------

/** Mirrors the closed vocabulary in `app/schemas/report.py`, least to most restricted. */
export const CLASSIFICATIONS = ["Public", "Internal", "Confidential"];

/**
 * Classification is encoded by an **icon**, not a hue.
 *
 * It is a state, so under this app's colour rule it would be entitled to one —
 * but red already means critical severity here, and a second meaning for the
 * same colour dilutes both. On paper the caveat gets red because it sits alone
 * in the page furniture with nothing to be confused with; on screen it sits
 * two inches from a severity badge.
 *
 * `shareable` is the UI's copy of the server rule, used only to decide what the
 * share dialog says before you press the button. The server decides.
 */
const CLASSIFICATION_TOKENS = {
  Public: {
    key: "Public",
    label: "Public",
    icon: "globe",
    shareable: true,
    description: "May be shared outside the organisation.",
  },
  Internal: {
    key: "Internal",
    label: "Internal",
    icon: "building",
    shareable: true,
    description: "May be shared by link with people outside the app.",
  },
  Confidential: {
    key: "Confidential",
    label: "Confidential",
    icon: "lock",
    shareable: false,
    description: "Sharing by link requires a written justification, which is recorded.",
  },
};

export function classificationToken(value) {
  return CLASSIFICATION_TOKENS[value] ?? { key: value, label: value || "—", icon: "building", shareable: true, description: "" };
}

// --- Primitives -----------------------------------------------------------

export function formatBytes(bytes) {
  const value = Number(bytes);
  if (!Number.isFinite(value) || value <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  const exponent = Math.min(Math.floor(Math.log(value) / Math.log(1024)), units.length - 1);
  const scaled = value / 1024 ** exponent;
  return `${scaled >= 10 || exponent === 0 ? Math.round(scaled) : scaled.toFixed(1)} ${units[exponent]}`;
}

const DATE_TIME = new Intl.DateTimeFormat(undefined, {
  year: "numeric",
  month: "short",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});

export function formatDateTime(value) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? String(value) : DATE_TIME.format(date);
}

const RELATIVE = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });
const UNITS = [
  ["year", 31_536_000],
  ["month", 2_592_000],
  ["day", 86_400],
  ["hour", 3600],
  ["minute", 60],
];

export function formatRelative(value) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);

  const seconds = (date.getTime() - Date.now()) / 1000;
  for (const [unit, size] of UNITS) {
    if (Math.abs(seconds) >= size) {
      return RELATIVE.format(Math.round(seconds / size), unit);
    }
  }
  return "just now";
}

/** Shorten a UUID for display. The full value stays available on hover. */
export function shortId(id) {
  return id ? String(id).slice(0, 8) : "—";
}

export function initials(user) {
  if (!user) return "?";
  const first = user.first_name?.[0] ?? "";
  const last = user.last_name?.[0] ?? "";
  return (first + last).toUpperCase() || user.email?.[0]?.toUpperCase() || "?";
}

export function fullName(user) {
  if (!user) return "";
  return [user.first_name, user.last_name].filter(Boolean).join(" ") || user.email;
}

/** Fields the LLM is allowed to leave null render as an em dash, never "null". */
export function orDash(value) {
  if (value === null || value === undefined || value === "") return "—";
  return value;
}
