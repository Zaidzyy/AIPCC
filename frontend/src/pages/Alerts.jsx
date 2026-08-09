import { BellOff, Check, ExternalLink, RotateCcw, ShieldAlert, Trash2 } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";

import { PageHeader } from "@/components/common/PageHeader";
import {
  Button,
  Card,
  EmptyState,
  ErrorState,
  SeverityBadge,
  SkeletonRows,
  Tabs,
  TabsList,
  TabsTrigger,
  Tooltip,
  useToast,
} from "@/components/ui";
import { useAlerts, useDeleteAlert, useSetAlertStatus } from "@/hooks/queries";
import { errorMessage } from "@/lib/apiClient";
import { formatDateTime, formatRelative, severityToken, shortId } from "@/lib/format";

const FILTERS = [
  { value: "open", label: "Open" },
  { value: "resolved", label: "Resolved" },
  { value: "all", label: "All" },
];

/**
 * Alerts raised by the n8n workflows.
 *
 * Ordered newest first and filtered to open by default, because the question
 * this page answers is "what still needs me", not "what has ever happened".
 */
export function Alerts() {
  const [filter, setFilter] = useState("open");
  const query = useAlerts(filter === "all" ? undefined : filter);
  const setStatus = useSetAlertStatus();
  const remove = useDeleteAlert();
  const { toast } = useToast();

  async function run(action, promise, title) {
    try {
      await promise;
      toast({ variant: "success", title });
    } catch (error) {
      toast({ variant: "error", title: `${action} failed`, description: errorMessage(error) });
    }
  }

  return (
    <>
      <PageHeader
        eyebrow="Monitoring"
        title="Security alerts"
        description="Raised by the n8n integrity and orchestration workflows against your reports."
      />

      <Tabs value={filter} onValueChange={setFilter} className="mb-5">
        <TabsList>
          {FILTERS.map((option) => (
            <TabsTrigger key={option.value} value={option.value}>
              {option.label}
            </TabsTrigger>
          ))}
        </TabsList>
      </Tabs>

      {query.isError ? (
        <Card>
          <ErrorState error={query.error} title="Could not load alerts" onRetry={query.refetch} />
        </Card>
      ) : query.isPending ? (
        <Card>
          <SkeletonRows rows={4} columns={3} />
        </Card>
      ) : query.data.length === 0 ? (
        <Card>
          <EmptyState
            icon={filter === "open" ? BellOff : ShieldAlert}
            title={
              filter === "open"
                ? "No open alerts"
                : filter === "resolved"
                  ? "Nothing resolved yet"
                  : "No alerts yet"
            }
            description={
              filter === "open"
                ? "Nothing is waiting on you. The FIM engine raises an alert here when a report's source log stops matching its sealed hash."
                : "Alerts appear here once an n8n workflow has run against your reports."
            }
          />
        </Card>
      ) : (
        <ul className="space-y-3">
          {query.data.map((alert) => (
            <AlertRow
              key={alert.alert_id}
              alert={alert}
              busy={setStatus.isPending || remove.isPending}
              onToggle={() =>
                run(
                  "Update",
                  setStatus.mutateAsync({
                    alertId: alert.alert_id,
                    status: alert.status === "open" ? "resolved" : "open",
                  }),
                  alert.status === "open" ? "Alert resolved" : "Alert reopened",
                )
              }
              onDelete={() =>
                run("Delete", remove.mutateAsync(alert.alert_id), "Alert deleted")
              }
            />
          ))}
        </ul>
      )}
    </>
  );
}

function AlertRow({ alert, busy, onToggle, onDelete }) {
  const token = severityToken(alert.severity);
  const resolved = alert.status === "resolved";

  return (
    <li>
      <Card
        className={
          // A resolved alert is dimmed rather than hidden: it is still part of
          // the record, it just is not asking for anything.
          resolved ? "opacity-60 transition-opacity hover:opacity-100" : undefined
        }
      >
        {/* The severity rule is the one coloured element on the row. */}
        <div className="flex gap-0">
          <span className={`w-0.5 shrink-0 rounded-l-lg ${token.bg}`} aria-hidden="true" />
          <div className="min-w-0 flex-1 px-5 py-4">
            <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
              <SeverityBadge level={alert.severity} />
              <span className="eyebrow">{alert.source}</span>
              <Tooltip content={formatDateTime(alert.created_at)}>
                <span className="text-xs text-ink-faint">{formatRelative(alert.created_at)}</span>
              </Tooltip>
              {resolved && (
                <span className="text-xs text-ink-faint">
                  · resolved {formatRelative(alert.resolved_at)}
                </span>
              )}
            </div>

            <p className="mt-2.5 text-sm leading-relaxed text-ink">{alert.message}</p>

            <div className="mt-3 flex flex-wrap items-center gap-2">
              {alert.report_id && (
                <Button variant="ghost" size="sm" className="-ml-2" asChild>
                  <Link to={`/reports/${alert.report_id}`}>
                    <ExternalLink />
                    Report {shortId(alert.report_id)}
                  </Link>
                </Button>
              )}
              <Button variant="ghost" size="sm" disabled={busy} onClick={onToggle}>
                {resolved ? <RotateCcw /> : <Check />}
                {resolved ? "Reopen" : "Resolve"}
              </Button>
              <Button variant="ghost" size="sm" disabled={busy} onClick={onDelete}>
                <Trash2 />
                Delete
              </Button>
            </div>
          </div>
        </div>
      </Card>
    </li>
  );
}
