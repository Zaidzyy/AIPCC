/**
 * Grouping a report's citations for rendering.
 *
 * A plain module rather than an export from `Evidence.jsx`, because
 * `react-refresh/only-export-components` is on for feature components in this
 * project and a non-component export there costs component state on every
 * save. See CLAUDE.md > Phase 7.
 */

/**
 * Group a report's flat evidence list by the finding it belongs to.
 *
 * Returns `null` when the report carries no evidence array at all — which is
 * how the public share view arrives, and what makes every disclosure vanish
 * there. That is deliberate: a share link grants read of a *report*, and
 * shipping the raw log excerpts with it would hand the holder more of the
 * source data than the report itself contains.
 *
 * An empty array for a finding is the opposite case and means something quite
 * different: the model produced that finding and cited nothing valid for it.
 */
export function groupEvidence(report) {
  if (!Array.isArray(report?.evidence)) return null;

  const byItem = new Map();
  for (const row of report.evidence) {
    const existing = byItem.get(row.item_id);
    if (existing) existing.push(row);
    else byItem.set(row.item_id, [row]);
  }
  return byItem;
}
