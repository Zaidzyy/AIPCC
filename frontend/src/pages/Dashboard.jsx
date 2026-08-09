import { ArrowRight, FileText, Database, Sparkles } from "lucide-react";
import { Link } from "react-router-dom";

import { AmbientVideo } from "@/components/common/AmbientVideo";
import { PageHeader } from "@/components/common/PageHeader";
import { SeveritySpine } from "@/components/common/SeveritySpine";
import {
  Button,
  Card,
  CardBody,
  CardHeader,
  CardTitle,
  EmptyState,
  ErrorState,
  Skeleton,
  StatusBadge,
} from "@/components/ui";
import { useAuth } from "@/context/AuthContext";
import { useDocuments, useReport, useReports } from "@/hooks/queries";
import { formatRelative, severityCounts, statusToken } from "@/lib/format";

export function Dashboard() {
  const { user } = useAuth();
  const reports = useReports();
  const documents = useDocuments();

  const latestId = reports.data?.[0]?.report_id;
  const latest = useReport(latestId);

  const failed = reports.data?.filter((r) => r.status === "failed").length ?? 0;
  const partial = reports.data?.filter((r) => r.status === "partial").length ?? 0;

  return (
    <>
      <PageHeader
        eyebrow="Analysis"
        title={`Welcome back, ${user?.first_name ?? "analyst"}`}
        description="Ingested logs, generated reports and their current state."
        actions={
          <Button variant="primary" asChild>
            <Link to="/generate">
              <Sparkles />
              Generate report
            </Link>
          </Button>
        }
      />

      {/* The threat-globe loop is the only video on this screen, and it sits
          behind the numbers rather than beside them — manifest rules 1 and 2. */}
      <section className="relative mb-6 overflow-hidden rounded-lg border border-line">
        <AmbientVideo clip="threat-globe" opacity="opacity-30" scrim="bg-void/78" />
        <div className="relative grid gap-px bg-line/60 sm:grid-cols-3">
          <Stat
            label="Reports"
            value={reports.data?.length}
            loading={reports.isPending}
            icon={FileText}
          />
          <Stat
            label="Documents ingested"
            value={documents.data?.length}
            loading={documents.isPending}
            icon={Database}
          />
          <Stat
            label="Needing attention"
            value={failed + partial}
            loading={reports.isPending}
            hint={
              failed + partial > 0
                ? `${failed} failed · ${partial} partial`
                : "All reports complete"
            }
            tone={failed > 0 ? "critical" : partial > 0 ? "medium" : "ok"}
          />
        </div>
      </section>

      <div className="grid gap-6 lg:grid-cols-[1.4fr_1fr]">
        <LatestReport summary={reports.data?.[0]} detail={latest} loading={reports.isPending} />
        <RecentReports query={reports} />
      </div>
    </>
  );
}

function Stat({ label, value, hint, loading, icon: Icon, tone }) {
  const toneClass = {
    critical: "text-critical",
    medium: "text-medium",
    ok: "text-ok",
  }[tone];

  return (
    <div className="bg-surface/70 px-5 py-5 backdrop-blur-[2px]">
      <div className="flex items-center gap-2">
        {Icon && <Icon className="size-3.5 text-ink-faint" aria-hidden="true" />}
        <p className="eyebrow">{label}</p>
      </div>
      {loading ? (
        <Skeleton className="mt-2.5 h-8 w-16" />
      ) : (
        <p
          className={`mt-1.5 font-mono text-3xl font-semibold tabular-nums tracking-tight ${
            toneClass ?? "text-ink"
          }`}
        >
          {value ?? 0}
        </p>
      )}
      {hint && !loading && <p className="mt-1 text-[0.8125rem] text-ink-faint">{hint}</p>}
    </div>
  );
}

function LatestReport({ summary, detail, loading }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Most recent report</CardTitle>
        {summary && (
          <Button variant="ghost" size="sm" asChild>
            <Link to={`/reports/${summary.report_id}`}>
              Open
              <ArrowRight />
            </Link>
          </Button>
        )}
      </CardHeader>

      {loading ? (
        <CardBody className="space-y-3">
          <Skeleton className="h-5 w-2/3" />
          <Skeleton className="h-1.5 w-full" />
          <Skeleton className="h-3.5 w-1/3" />
        </CardBody>
      ) : !summary ? (
        <EmptyState
          icon={FileText}
          title="No reports yet"
          description="Upload a log file and generate your first report to see it here."
          action={
            <Button variant="primary" size="sm" asChild>
              <Link to="/generate">Generate a report</Link>
            </Button>
          }
        />
      ) : (
        <CardBody className="space-y-4">
          <div>
            <p className="font-mono text-base font-medium text-ink">{summary.report_name}</p>
            <div className="mt-1.5 flex items-center gap-3">
              <StatusBadge status={summary.status} />
              <span className="text-[0.8125rem] text-ink-faint">
                {formatRelative(summary.generated_at)}
              </span>
            </div>
          </div>

          {/* The spine needs section data, which only the detail response
              carries — the list endpoint returns summaries. */}
          {detail.isPending ? (
            <Skeleton className="h-1.5 w-full" />
          ) : detail.data ? (
            <SeveritySpine counts={risksOf(detail.data)} showLegend />
          ) : null}
        </CardBody>
      )}
    </Card>
  );
}

function RecentReports({ query }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Activity</CardTitle>
      </CardHeader>

      {query.isError ? (
        <ErrorState error={query.error} title="Could not load reports" onRetry={query.refetch} />
      ) : query.isPending ? (
        <CardBody className="space-y-3.5">
          {Array.from({ length: 4 }, (_, index) => (
            <Skeleton key={index} className="h-4 w-full" />
          ))}
        </CardBody>
      ) : query.data.length === 0 ? (
        <EmptyState title="Nothing yet" description="Generated reports will appear here." />
      ) : (
        <ul className="divide-y divide-line/70">
          {query.data.slice(0, 6).map((report) => (
            <li key={report.report_id}>
              <Link
                to={`/reports/${report.report_id}`}
                className="flex items-center justify-between gap-3 px-5 py-3 transition-colors hover:bg-raised/60"
              >
                <span className="min-w-0">
                  <span className="block truncate text-sm text-ink">{report.report_name}</span>
                  <span className="text-xs text-ink-faint">
                    {formatRelative(report.generated_at)}
                  </span>
                </span>
                <span
                  className={`size-1.5 shrink-0 rounded-full ${statusToken(report.status).dot}`}
                  aria-label={statusToken(report.status).label}
                />
              </Link>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

/** Attack risks and general risks share the `risk_level` field. */
function risksOf(report) {
  const items = [
    ...(report.sections?.attack_types ?? []),
    ...(report.sections?.general_risk_assessment ?? []),
  ];
  return severityCounts(items);
}
