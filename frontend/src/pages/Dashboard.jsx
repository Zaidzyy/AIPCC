import { Activity, ArrowRight, Database, FileText, ShieldAlert, Sparkles, TriangleAlert } from "lucide-react";
import { Suspense, lazy, useState } from "react";
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
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Skeleton,
  StatusBadge,
} from "@/components/ui";
import { useAuth } from "@/context/AuthContext";
import {
  useAnomaliesOverTime,
  useDashboardSummary,
  useReport,
  useReports,
  useReportsOverTime,
  useSeverityBreakdown,
  useTopAttackTypes,
} from "@/hooks/queries";
import { formatRelative, severityCounts, statusToken } from "@/lib/format";

/**
 * Recharts is the largest dependency in the app and only this route draws
 * charts, so it lives behind a lazy boundary and downloads alongside the
 * aggregate requests rather than in front of the first paint.
 */
const ChartGrid = lazy(() => import("@/components/charts/ChartGrid"));

const WINDOWS = [
  { value: "7", label: "7 days" },
  { value: "30", label: "30 days" },
  { value: "90", label: "90 days" },
];

/**
 * Every number on this page comes from a `GROUP BY` on the server, scoped to
 * the caller. Nothing is counted in the browser, and nothing is a placeholder —
 * if an aggregate is zero it is because there is nothing to count.
 */
export function Dashboard() {
  const { user, isAdmin } = useAuth();
  const [window, setWindow] = useState("30");
  const days = Number(window);

  const summary = useDashboardSummary();
  const reportsOverTime = useReportsOverTime(days);
  const severity = useSeverityBreakdown();
  const attacks = useTopAttackTypes(8);
  const anomalies = useAnomaliesOverTime(days);
  const reports = useReports();

  const latestId = reports.data?.[0]?.report_id;
  const latest = useReport(latestId);

  // A brand-new install has nothing to chart. Four empty chart cards read as a
  // broken page; one deliberate panel that says what to do next does not.
  const nothingYet = summary.data?.total_reports === 0;

  const windowPicker = (
    <Select value={window} onValueChange={setWindow}>
      <SelectTrigger className="h-8 w-28 text-xs" aria-label="Time window">
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {WINDOWS.map((option) => (
          <SelectItem key={option.value} value={option.value}>
            {option.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );

  return (
    <>
      <PageHeader
        eyebrow="Analysis"
        title={`Welcome back, ${user?.first_name ?? "analyst"}`}
        description={
          isAdmin
            ? "Aggregates across every analyst's reports."
            : "Aggregates across the logs and reports you own."
        }
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
        <div className="relative grid gap-px bg-line/60 sm:grid-cols-2 xl:grid-cols-4">
          <Stat
            label="Reports"
            value={summary.data?.total_reports}
            query={summary}
            icon={FileText}
          />
          <Stat
            label="Critical findings"
            value={summary.data?.critical_findings}
            query={summary}
            icon={ShieldAlert}
            tone={summary.data?.critical_findings > 0 ? "critical" : undefined}
            hint="Across attack risks and risk assessments"
          />
          <Stat
            label="Documents"
            value={summary.data?.documents_ingested}
            query={summary}
            icon={Database}
          />
          <Stat
            label="Needs attention"
            value={summary.data?.attention_required}
            query={summary}
            icon={TriangleAlert}
            tone={attentionTone(summary.data)}
            hint={
              summary.data?.attention_required
                ? "Reports that came back partial or failed"
                : // "Every report completed" is only true if there are any.
                  summary.data?.total_reports
                  ? "Every report completed"
                  : undefined
            }
          />
        </div>
      </section>

      {summary.isError ? (
        <Card className="mb-6">
          <ErrorState
            error={summary.error}
            title="Could not load dashboard totals"
            onRetry={summary.refetch}
          />
        </Card>
      ) : nothingYet ? (
        <FirstRun hasDocuments={summary.data.documents_ingested > 0} />
      ) : (
        <div className="mb-6 grid gap-6 xl:grid-cols-[1.5fr_1fr]">
          <Suspense fallback={<ChartPlaceholders />}>
            <ChartGrid
              query={{ reportsOverTime, severity, attacks, anomalies }}
              days={days}
              windowPicker={windowPicker}
            />
          </Suspense>
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-[1.4fr_1fr]">
        <LatestReport summary={reports.data?.[0]} detail={latest} loading={reports.isPending} />
        <RecentReports query={reports} />
      </div>
    </>
  );
}

/** Green means "checked and clean", so it is only earned once there is
 *  something to have checked. */
function attentionTone(summary) {
  if (!summary?.total_reports) return undefined;
  return summary.attention_required > 0 ? "medium" : "ok";
}

function Stat({ label, value, hint, query, icon: Icon, tone }) {
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
      {query.isPending ? (
        <Skeleton className="mt-2.5 h-8 w-16" />
      ) : query.isError ? (
        // An unreadable total is not zero. Showing "0" here would be the one
        // kind of lie a security dashboard cannot afford.
        <p className="mt-1.5 font-mono text-3xl font-semibold text-ink-faint">—</p>
      ) : (
        <p
          className={`mt-1.5 font-mono text-3xl font-semibold tabular-nums tracking-tight ${
            toneClass ?? "text-ink"
          }`}
        >
          {value ?? 0}
        </p>
      )}
      {hint && !query.isPending && !query.isError && (
        <p className="mt-1 text-[0.8125rem] text-ink-faint">{hint}</p>
      )}
    </div>
  );
}

/** Holds the grid's shape while the chart chunk downloads, so the KPI row and
 *  the report list below it do not jump when the charts arrive. */
function ChartPlaceholders() {
  return (
    <>
      {[230, 230, 290, 230].map((height, index) => (
        <Card key={index}>
          <CardHeader>
            <Skeleton className="h-4 w-40" />
          </CardHeader>
          <CardBody>
            <Skeleton style={{ height }} className="w-full" />
          </CardBody>
        </Card>
      ))}
    </>
  );
}

/** What the dashboard shows before it has anything to aggregate. */
function FirstRun({ hasDocuments }) {
  return (
    <Card className="mb-6">
      <CardHeader>
        <CardTitle>Nothing to chart yet</CardTitle>
      </CardHeader>
      <EmptyState
        icon={Activity}
        title={hasDocuments ? "Your logs are uploaded" : "Start by uploading a log"}
        description={
          hasDocuments
            ? "Generate a report and the charts on this page — volume, severity, attack frequency and anomalies — start filling in."
            : "Upload a CSV, JSON, TXT or LOG file, generate a report from it, and this page becomes a live view of what was found."
        }
        action={
          <Button variant="primary" size="sm" asChild>
            <Link to="/generate">{hasDocuments ? "Generate a report" : "Upload a log"}</Link>
          </Button>
        }
      />
    </Card>
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
