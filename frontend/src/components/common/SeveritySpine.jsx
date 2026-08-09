import { SEVERITIES, severityToken } from "@/lib/format";
import { cn } from "@/lib/utils";

/**
 * The severity spine — the app's signature element.
 *
 * A single thin bar showing how a set of findings distributes across the
 * severity ladder. It appears on report cards, on the report header and on the
 * dashboard, so the same shape means the same thing everywhere and a report's
 * profile is readable before any text is.
 *
 * It is deliberately unlabelled at rest: the point is the silhouette. Counts
 * are available on hover and to screen readers.
 */
export function SeveritySpine({ counts, className, height = "h-1.5", showLegend = false }) {
  const segments = SEVERITIES.map((key) => ({
    key,
    token: severityToken(key),
    count: counts?.[key] ?? 0,
  })).reverse(); // Critical first — the eye should land on the worst.

  const unknown = counts?.unknown ?? 0;
  const total = segments.reduce((sum, segment) => sum + segment.count, 0) + unknown;

  if (total === 0) {
    return (
      <div className={cn("w-full rounded-full bg-line", height, className)} aria-hidden="true" />
    );
  }

  const label = segments
    .filter((segment) => segment.count > 0)
    .map((segment) => `${segment.count} ${segment.token.label.toLowerCase()}`)
    .join(", ");

  return (
    <div className={cn("space-y-2", className)}>
      <div
        className={cn("flex w-full gap-px overflow-hidden rounded-full", height)}
        role="img"
        aria-label={`Severity distribution: ${label || "unrated"}`}
      >
        {segments
          .filter((segment) => segment.count > 0)
          .map(({ key, token, count }) => (
            <div
              key={key}
              className={cn(token.bg, "first:rounded-l-full last:rounded-r-full")}
              style={{ width: `${(count / total) * 100}%` }}
              title={`${count} ${token.label.toLowerCase()}`}
            />
          ))}
        {unknown > 0 && (
          <div
            className="bg-line-strong first:rounded-l-full last:rounded-r-full"
            style={{ width: `${(unknown / total) * 100}%` }}
            title={`${unknown} unrated`}
          />
        )}
      </div>

      {showLegend && (
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5">
          {segments.map(({ key, token, count }) => (
            <span key={key} className="inline-flex items-center gap-1.5">
              <span className={cn("size-1.5 rounded-full", token.bg)} aria-hidden="true" />
              <span className="eyebrow">{token.label}</span>
              <span className="font-mono text-xs tabular-nums text-ink">{count}</span>
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
