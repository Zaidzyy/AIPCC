import { TriangleAlert } from "lucide-react";

import { foldDetections } from "@/lib/attack";
import { cn } from "@/lib/utils";

/**
 * The enterprise ATT&CK matrix: tactics as columns, techniques as cells.
 *
 * **Readability was the decision this component exists to make.** The full
 * enterprise matrix is 823 techniques; drawn flat it is a wall nobody reads.
 * Three things keep it scannable, and each was chosen over the alternatives:
 *
 * 1. **Sub-techniques do not get cells.** 679 placed techniques collapse to
 *    211 parents, and a parent shows a marker when the detection was on one of
 *    its children. This is how MITRE draws it, and it is why no virtualisation
 *    is needed — the whole grid is ~245 cells.
 * 2. **Columns are always all fourteen**, even the empty ones. The recognisable
 *    thing about this diagram is its shape; hiding the quiet tactics would
 *    redraw the shape per report and lose the "nothing was seen here" reading,
 *    which on a security page is information.
 * 3. **A density switch, not a scroll hack.** "Detected" shows only the cells
 *    with findings behind them — the honest default for a report — and "Full"
 *    draws every technique so an analyst can see the coverage gap.
 *
 * Colour: frequency is rendered as an ink ramp, not a hue. That is this app's
 * standing rule (Phase 4: a taller bar already says "more", and spending a hue
 * on volume dilutes every hue that means something). The only chroma on the
 * grid is amber, and it means one thing — the model's name for this technique
 * did not match ATT&CK.
 */

/**
 * Five bands, written out in full. Tailwind generates utilities by scanning
 * source text, so a class assembled at runtime silently never gets a rule —
 * a bug this project has already paid for once (CLAUDE.md, Phase 3).
 */
const BANDS = [
  "bg-ink/10 text-ink border-ink/15",
  "bg-ink/20 text-ink border-ink/25",
  "bg-ink/35 text-ink border-ink/35",
  "bg-ink/60 text-void border-ink/50",
  "bg-ink/85 text-void border-ink/70",
];

function band(count, max) {
  if (count <= 0) return null;
  if (max <= 1) return BANDS[BANDS.length - 1];
  // Linear over the observed range, so the busiest technique on *this* page is
  // always the darkest cell — an absolute scale would render a quiet week as
  // an empty matrix.
  const step = Math.ceil((count / max) * BANDS.length);
  return BANDS[Math.min(step, BANDS.length) - 1];
}

export function MatrixGrid({ grid, detections, dense, onSelect }) {
  const folded = foldDetections(detections);
  const max = Math.max(1, ...[...folded.values()].map((entry) => entry.total));

  return (
    <div className="overflow-x-auto">
      <div className="flex min-w-max gap-2 pb-2">
        {grid.tactics.map((tactic) => {
          const cells = tactic.techniques
            .map((technique) => ({ technique, hit: folded.get(technique.technique_id) }))
            .filter((cell) => (dense ? Boolean(cell.hit) : true));

          if (dense) cells.sort((a, b) => b.hit.total - a.hit.total);

          return (
            <section key={tactic.shortname} className="w-[13.5rem] shrink-0">
              <header className="mb-2 border-b border-line-strong pb-2">
                <p className="eyebrow truncate" title={tactic.description || tactic.name}>
                  {tactic.name}
                </p>
                <p className="mt-1 font-mono text-[0.6875rem] text-ink-faint tabular-nums">
                  {tactic.tactic_id} · {cells.length}
                  {dense ? " detected" : ` of ${tactic.techniques.length}`}
                </p>
              </header>

              <div className="space-y-1">
                {cells.length === 0 ? (
                  // Not an empty div: "no technique in this tactic was seen"
                  // is a finding on a security page, and it has to read as one.
                  <p className="rounded-md border border-dashed border-line px-2 py-3 text-center text-[0.6875rem] text-ink-faint">
                    No detections
                  </p>
                ) : (
                  cells.map(({ technique, hit }) => (
                    <Cell
                      key={technique.technique_id}
                      technique={technique}
                      hit={hit}
                      max={max}
                      onSelect={onSelect}
                    />
                  ))
                )}
              </div>
            </section>
          );
        })}
      </div>
    </div>
  );
}

function Cell({ technique, hit, max, onSelect }) {
  const detected = Boolean(hit);
  const shade = detected ? band(hit.total, max) : null;

  return (
    <button
      type="button"
      disabled={!detected}
      onClick={() => detected && onSelect(technique, hit)}
      className={cn(
        "w-full rounded-md border px-2 py-1.5 text-left transition-colors",
        detected
          ? cn(shade, "cursor-pointer hover:border-ink focus-visible:border-ink")
          : "cursor-default border-line/70 bg-surface/40 text-ink-faint",
        detected && hit.unverified && "border-medium/70",
      )}
      title={
        detected
          ? `${technique.technique_id} · ${technique.name} · ${hit.total} detection(s)`
          : `${technique.technique_id} · ${technique.name}`
      }
    >
      <span className="flex items-start justify-between gap-1.5">
        <span className="min-w-0">
          <span className="block font-mono text-[0.625rem] leading-tight opacity-70">
            {technique.technique_id}
          </span>
          <span className="mt-0.5 block text-[0.75rem] leading-snug">{technique.name}</span>
        </span>
        {detected && (
          <span className="flex shrink-0 items-center gap-1">
            {hit.unverified && (
              <TriangleAlert className="size-3 text-medium" aria-label="Unverified" />
            )}
            <span className="font-mono text-[0.6875rem] font-semibold tabular-nums">
              {hit.total}
            </span>
          </span>
        )}
      </span>
      {detected && hit.subs.length > 0 && (
        <span className="mt-1 block font-mono text-[0.625rem] opacity-70">
          {hit.subs.length} sub-technique{hit.subs.length === 1 ? "" : "s"}
        </span>
      )}
    </button>
  );
}
