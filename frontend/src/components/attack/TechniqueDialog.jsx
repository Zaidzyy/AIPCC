import { ExternalLink, TriangleAlert } from "lucide-react";
import { Link } from "react-router-dom";

import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  SeverityBadge,
} from "@/components/ui";
import { formatDateTime } from "@/lib/format";

/**
 * What is behind one cell of the matrix.
 *
 * The point of clicking a cell is to get from "this technique was detected" to
 * the findings that say so, so every row here links to the report it came
 * from. A matrix that cannot be traced back to evidence is a picture.
 *
 * The technique name shown is always the catalogue's; the model's own wording
 * appears only as the finding's title, where it belongs, and never as the
 * label on a technique.
 */
export function TechniqueDialog({ selection, onClose }) {
  const open = Boolean(selection);
  const technique = selection?.technique;
  const hit = selection?.hit;

  return (
    <Dialog open={open} onOpenChange={(next) => !next && onClose()}>
      <DialogContent className="max-w-2xl">
        {selection && (
          <>
            <DialogHeader>
              <DialogTitle className="flex flex-wrap items-center gap-2">
                <span className="font-mono text-ink-dim">{technique.technique_id}</span>
                {technique.name}
              </DialogTitle>
              <DialogDescription>
                {hit.total} detection{hit.total === 1 ? "" : "s"} across{" "}
                {hit.detections.length} technique
                {hit.detections.length === 1 ? "" : "s"} in this scope.{" "}
                <a
                  className="inline-flex items-center gap-1 text-ink underline underline-offset-2"
                  href={`https://attack.mitre.org/techniques/${technique.technique_id}/`}
                  target="_blank"
                  rel="noreferrer"
                >
                  ATT&amp;CK entry
                  <ExternalLink className="size-3" aria-hidden="true" />
                </a>
              </DialogDescription>
            </DialogHeader>

            <DialogBody className="space-y-5">
              {hit.detections.map((detection) => (
                <section key={detection.technique_id} className="space-y-2">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-mono text-xs text-ink">
                      {detection.technique_id}
                    </span>
                    <span className="text-sm text-ink-dim">{detection.name}</span>
                    <span className="font-mono text-xs text-ink-faint tabular-nums">
                      ×{detection.count}
                    </span>
                  </div>

                  {!detection.verified && (
                    // Never hidden and never softened: the id is real, the
                    // model's name for it was not, and a reader has to know
                    // which half of the cell to trust.
                    <p className="flex items-start gap-2 rounded-md border border-medium/35 bg-medium/10 px-3 py-2 text-xs text-medium">
                      <TriangleAlert className="mt-px size-3.5 shrink-0" aria-hidden="true" />
                      Unverified — {detection.issue}
                    </p>
                  )}

                  <ul className="space-y-1">
                    {detection.sources.map((source, index) => (
                      <li
                        // One report can hold two findings that map to the same
                        // technique, so the report id alone is not unique here.
                        key={`${source.report_id}-${index}`}
                        className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-line bg-surface px-3 py-2"
                      >
                        <div className="min-w-0">
                          <p className="truncate text-sm text-ink">
                            {source.attack_name || "Unnamed finding"}
                          </p>
                          <p className="mt-0.5 truncate text-xs text-ink-faint">
                            {source.report_name} · {formatDateTime(source.generated_at)}
                          </p>
                        </div>
                        <div className="flex shrink-0 items-center gap-2">
                          <SeverityBadge level={source.risk_level} />
                          <Link
                            to={`/reports/${source.report_id}`}
                            className="text-xs text-ink underline underline-offset-2"
                            onClick={onClose}
                          >
                            Open report
                          </Link>
                        </div>
                      </li>
                    ))}
                  </ul>
                </section>
              ))}
            </DialogBody>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}
