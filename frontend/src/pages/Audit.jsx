import { ChevronLeft, ChevronRight, ScrollText, ShieldCheck, X } from "lucide-react";
import { useState } from "react";

import { PageHeader } from "@/components/common/PageHeader";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorState,
  Input,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  SkeletonRows,
  TBody,
  TD,
  TH,
  THead,
  TR,
  Table,
  Tooltip,
} from "@/components/ui";
import { useAuditFilters, useAuditLog } from "@/hooks/queries";
import {
  actionLabel,
  actionSubject,
  formatDateTime,
  formatRelative,
  outcomeToken,
  shortId,
} from "@/lib/format";

const PAGE_SIZE = 25;
const ANY = "__any__";

/**
 * The audit trail.
 *
 * Read-only, and it says so — there is no resolve, no dismiss and no delete,
 * because the table behind it is append-only and a control that looked like it
 * could change a row would be lying about the guarantee. The one affordance is
 * filtering.
 *
 * Newest first, because the question this page answers is "what just
 * happened", and paginated rather than infinite because an investigator needs
 * to be able to say which page they were looking at.
 */
export function Audit() {
  const [action, setAction] = useState(ANY);
  const [outcome, setOutcome] = useState(ANY);
  const [actor, setActor] = useState("");
  const [offset, setOffset] = useState(0);

  // Debouncing the actor field would add a dependency-shaped problem for one
  // input; committing on submit means one request per intent instead of one
  // per keystroke, and the button says when it has been applied.
  const [appliedActor, setAppliedActor] = useState("");

  const params = {
    limit: PAGE_SIZE,
    offset,
    ...(action !== ANY && { action }),
    ...(outcome !== ANY && { outcome }),
    ...(appliedActor && { actor: appliedActor }),
  };

  const query = useAuditLog(params);
  const filters = useAuditFilters();

  const filtered = action !== ANY || outcome !== ANY || Boolean(appliedActor);
  const total = query.data?.total ?? 0;

  function change(setter) {
    return (value) => {
      setter(value);
      // Any filter change invalidates the page number — page 3 of the old
      // result set is not page 3 of the new one.
      setOffset(0);
    };
  }

  function clear() {
    setAction(ANY);
    setOutcome(ANY);
    setActor("");
    setAppliedActor("");
    setOffset(0);
  }

  return (
    <>
      <PageHeader
        eyebrow="Administration"
        title="Audit log"
        description="Every security-relevant action, appended and never modified. Authentication, role and status changes, credentials, classification, sharing, integrity and export."
      />

      <Card className="mb-5">
        <form
          className="flex flex-wrap items-end gap-3 px-5 py-4"
          onSubmit={(event) => {
            event.preventDefault();
            setAppliedActor(actor.trim());
            setOffset(0);
          }}
        >
          <div className="min-w-52 flex-1 space-y-1.5">
            <label className="eyebrow" htmlFor="audit-actor">
              Actor
            </label>
            <Input
              id="audit-actor"
              value={actor}
              placeholder="Email, user id or source address"
              onChange={(event) => setActor(event.target.value)}
            />
          </div>

          <div className="w-56 space-y-1.5">
            <p className="eyebrow">Action</p>
            <Select value={action} onValueChange={change(setAction)}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={ANY}>Any action</SelectItem>
                {(filters.data?.actions ?? []).map((value) => (
                  <SelectItem key={value} value={value}>
                    {actionSubject(value)} · {actionLabel(value)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="w-40 space-y-1.5">
            <p className="eyebrow">Outcome</p>
            <Select value={outcome} onValueChange={change(setOutcome)}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={ANY}>Any outcome</SelectItem>
                {(filters.data?.outcomes ?? []).map((value) => (
                  <SelectItem key={value} value={value}>
                    {outcomeToken(value).label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <Button type="submit">Apply</Button>
          {filtered && (
            <Button type="button" variant="ghost" onClick={clear}>
              <X />
              Clear
            </Button>
          )}
        </form>
      </Card>

      <Card className="overflow-hidden">
        {query.isError ? (
          <ErrorState
            error={query.error}
            title="Could not load the audit log"
            onRetry={query.refetch}
          />
        ) : query.isPending ? (
          <SkeletonRows rows={8} columns={5} />
        ) : query.data.items.length === 0 ? (
          // Empty and "filtered to nothing" are different answers on a security
          // page: one means nothing has happened, the other means nothing
          // matches what you asked. Never the same message.
          <EmptyState
            icon={filtered ? ScrollText : ShieldCheck}
            title={filtered ? "No entries match these filters" : "Nothing recorded yet"}
            description={
              filtered
                ? "The log is not empty — no entry matches this actor, action or outcome."
                : "Sign-ins, role changes, exports and share links appear here as they happen."
            }
            action={
              filtered ? (
                <Button onClick={clear}>
                  <X />
                  Clear filters
                </Button>
              ) : null
            }
          />
        ) : (
          <Table>
            <THead>
              <TR className="hover:bg-transparent">
                <TH className="w-40">When</TH>
                <TH className="w-56">Action</TH>
                <TH>Actor</TH>
                <TH className="hidden w-48 lg:table-cell">Target</TH>
                <TH className="hidden w-36 xl:table-cell">Source</TH>
              </TR>
            </THead>
            <TBody>
              {query.data.items.map((entry) => (
                <AuditRow key={entry.audit_id} entry={entry} />
              ))}
            </TBody>
          </Table>
        )}
      </Card>

      {query.data?.items.length > 0 && (
        <div className="mt-4 flex items-center justify-between">
          <p className="text-xs text-ink-faint">
            {offset + 1}–{Math.min(offset + PAGE_SIZE, total)} of {total.toLocaleString()}
          </p>
          <div className="flex gap-2">
            <Button
              size="sm"
              disabled={offset === 0}
              onClick={() => setOffset((current) => Math.max(0, current - PAGE_SIZE))}
            >
              <ChevronLeft />
              Newer
            </Button>
            <Button
              size="sm"
              disabled={offset + PAGE_SIZE >= total}
              onClick={() => setOffset((current) => current + PAGE_SIZE)}
            >
              Older
              <ChevronRight />
            </Button>
          </div>
        </div>
      )}
    </>
  );
}

function AuditRow({ entry }) {
  const outcome = outcomeToken(entry.outcome);

  return (
    <TR>
      <TD className="align-middle">
        <Tooltip content={formatDateTime(entry.at)}>
          <span className="text-[0.8125rem] text-ink-dim">{formatRelative(entry.at)}</span>
        </Tooltip>
      </TD>

      <TD className="align-middle">
        <div className="flex items-center gap-2">
          {/* The one coloured element on the row, and it encodes the outcome. */}
          <span className={`size-1.5 shrink-0 rounded-full ${outcome.dot}`} aria-hidden="true" />
          <div className="min-w-0">
            <p className="truncate text-sm text-ink">{actionLabel(entry.action)}</p>
            {/* The raw id, because it is what you paste into a filter or find
                in the backend source — the label alone is not searchable. */}
            <p className="ident truncate text-[0.6875rem] text-ink-faint">{entry.action}</p>
          </div>
        </div>
      </TD>

      <TD className="align-middle">
        <div className="flex items-center gap-2">
          <span className="truncate text-[0.8125rem] text-ink">
            {entry.actor_label ?? "—"}
          </span>
          {/* A machine caller and the admin whose account it runs as look
              identical without this. */}
          {entry.actor_type === "api_key" && <Badge variant="outline">API key</Badge>}
          {entry.actor_type === "anonymous" && <Badge variant="outline">Unauthenticated</Badge>}
        </div>
      </TD>

      <TD className="hidden align-middle lg:table-cell">
        {entry.target_type ? (
          <span className="text-[0.8125rem] text-ink-dim">
            {entry.target_type} <span className="ident">{shortId(entry.target_id)}</span>
          </span>
        ) : (
          <span className="text-ink-faint">—</span>
        )}
        <Detail detail={entry.detail} />
      </TD>

      <TD className="hidden align-middle xl:table-cell">
        <span className="ident text-xs text-ink-faint">{entry.source_ip ?? "—"}</span>
      </TD>
    </TR>
  );
}

/**
 * The structured extras, rendered inline rather than behind an expander.
 *
 * These are the fields that carry the meaning — `from`/`to` on a role change,
 * the classification on an export — and they are already redacted and
 * length-capped server side, so there is nothing here worth hiding behind a
 * click on a page whose whole purpose is being read.
 */
function Detail({ detail }) {
  const entries = Object.entries(detail ?? {}).filter(([, value]) => value !== null);
  if (entries.length === 0) return null;

  return (
    <dl className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5">
      {entries.map(([key, value]) => (
        <div key={key} className="flex gap-1 text-[0.6875rem]">
          <dt className="text-ink-faint">{key.replace(/_/g, " ")}</dt>
          <dd className="ident text-ink-dim">{String(value)}</dd>
        </div>
      ))}
    </dl>
  );
}
