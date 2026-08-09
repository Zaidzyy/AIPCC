import { cva } from "class-variance-authority";

import { integrityToken, severityToken, statusToken } from "@/lib/format";
import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center gap-1.5 rounded-sm border px-1.5 py-0.5 " +
    "font-mono text-[0.6875rem] font-medium uppercase tracking-wider whitespace-nowrap",
  {
    variants: {
      variant: {
        neutral: "border-line-strong bg-raised text-ink-dim",
        outline: "border-line-strong bg-transparent text-ink-dim",
      },
    },
    defaultVariants: { variant: "neutral" },
  },
);

export function Badge({ className, variant, ...props }) {
  return <span className={cn(badgeVariants({ variant }), className)} {...props} />;
}

/**
 * The severity badge — the app's primary use of colour.
 *
 * Renders the tint, border and text from one token so a level can never be
 * shown in the wrong hue at one call site and the right hue at another.
 */
export function SeverityBadge({ level, className }) {
  const token = severityToken(level);
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-sm border px-1.5 py-0.5",
        "font-mono text-[0.6875rem] font-medium uppercase tracking-wider whitespace-nowrap",
        token.tint,
        token.border,
        token.text,
        className,
      )}
    >
      <span className={cn("size-1.5 rounded-full", token.bg)} aria-hidden="true" />
      {token.label}
    </span>
  );
}

/**
 * File-integrity state, from the n8n FIM engine.
 *
 * Bordered rather than bare, because unlike report status this is a claim
 * about evidence — a tampered source log is the strongest thing this screen
 * can say, and it should not read as a status word.
 */
export function IntegrityBadge({ state, className }) {
  const token = integrityToken(state);
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-sm border px-1.5 py-0.5",
        "font-mono text-[0.6875rem] font-medium uppercase tracking-wider whitespace-nowrap",
        token.tint,
        token.border,
        token.text,
        className,
      )}
      title={token.description}
    >
      <span className={cn("size-1.5 rounded-full", token.dot)} aria-hidden="true" />
      {token.label}
    </span>
  );
}

/** Report status, shown as a dot plus a word rather than a filled pill. */
export function StatusBadge({ status, className }) {
  const token = statusToken(status);
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 font-mono text-[0.6875rem] font-medium uppercase tracking-wider",
        token.text,
        className,
      )}
    >
      <span className={cn("size-1.5 rounded-full", token.dot)} aria-hidden="true" />
      {token.label}
    </span>
  );
}
