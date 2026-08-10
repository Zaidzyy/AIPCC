import { FileSearch, ShieldQuestion } from "lucide-react";

import { Tooltip } from "@/components/ui";

/**
 * The log content behind a finding.
 *
 * Built on native `<details>` rather than a Radix disclosure: there is one
 * per finding and a report can hold sixty, so sixty pieces of React state to
 * reproduce behaviour the browser already has correctly — including keyboard
 * operation and find-in-page reaching collapsed text — is a bad trade.
 *
 * **An ungrounded finding says so.** It is not hidden and the finding is not
 * dropped: the model claimed something and could not point at anything, and an
 * analyst is better served knowing that than seeing a claim with no marker at
 * all. Same rule as `UNKNOWN` integrity — an absence must never read as a
 * clean result.
 */
export function Evidence({ rows, compact = false }) {
  if (!rows) return null;

  if (rows.length === 0) {
    return (
      <Tooltip content="The model did not cite any log content this finding came from.">
        <span
          className={`inline-flex items-center gap-1.5 text-medium ${
            compact ? "text-[0.6875rem]" : "text-xs"
          }`}
        >
          <ShieldQuestion className="size-3.5" aria-hidden="true" />
          Ungrounded
        </span>
      </Tooltip>
    );
  }

  return (
    <details className={compact ? "" : "mt-4"}>
      <summary
        className={`inline-flex cursor-pointer list-none items-center gap-1.5 text-ink-dim transition-colors hover:text-ink ${
          compact ? "text-[0.6875rem]" : "text-xs"
        }`}
      >
        <FileSearch className="size-3.5 shrink-0" aria-hidden="true" />
        {rows.length} source{rows.length === 1 ? "" : "s"}
      </summary>

      <ul className="mt-2.5 space-y-2">
        {rows.map((row) => (
          <li key={row.evidence_id} className="rounded-md border border-line bg-void/60 p-3">
            <p className="eyebrow mb-1.5">
              {locator(row)} · chunk {row.chunk_id}
            </p>
            {/* The log text as it was, monospaced and scrollable rather than
                wrapped: a CSV row wrapped across four lines stops looking like
                a record and starts looking like prose. */}
            <pre className="max-h-44 overflow-auto whitespace-pre-wrap break-words font-mono text-[0.6875rem] leading-relaxed text-ink-dim">
              {row.excerpt}
            </pre>
          </li>
        ))}
      </ul>
    </details>
  );
}

/**
 * How a citation is described to a person: rows when the source was tabular,
 * lines when it was a log file, and neither when ingest could not establish
 * the mapping exactly — in which case it says so rather than guessing.
 */
function locator(row) {
  if (row.row_start !== null && row.row_start !== undefined) {
    return row.row_end !== null && row.row_end !== row.row_start
      ? `rows ${row.row_start}–${row.row_end}`
      : `row ${row.row_start}`;
  }
  if (row.line_start !== null && row.line_start !== undefined) {
    return row.line_end !== null && row.line_end !== row.line_start
      ? `lines ${row.line_start}–${row.line_end}`
      : `line ${row.line_start}`;
  }
  return "source";
}
