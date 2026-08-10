import { AlertTriangle, ArrowLeft, Trash2 } from "lucide-react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { SeveritySpine } from "@/components/common/SeveritySpine";
import { ClassificationSelect } from "@/components/report/ClassificationSelect";
import { GraphPanel } from "@/components/graph/GraphPanel";
import { ExportMenu } from "@/components/report/ExportMenu";
import { ReportBody } from "@/components/report/ReportBody";
import { ShareDialog } from "@/components/report/ShareDialog";
import {
  Button,
  Card,
  ErrorState,
  IntegrityBadge,
  LoadingState,
  Separator,
  Skeleton,
  StatusBadge,
  Tooltip,
  useToast,
} from "@/components/ui";
import { useDeleteReport, useExportReport, useReport } from "@/hooks/queries";
import { errorMessage } from "@/lib/apiClient";
import { formatDateTime, integrityToken, severityCounts, shortId } from "@/lib/format";

export function ReportDetail() {
  const { reportId } = useParams();
  const navigate = useNavigate();
  const { toast } = useToast();

  const query = useReport(reportId);
  const remove = useDeleteReport();
  const exportReport = useExportReport();

  if (query.isPending) return <DetailSkeleton />;

  if (query.isError) {
    return (
      <>
        <BackLink />
        <Card>
          <ErrorState
            error={query.error}
            title="Could not load this report"
            onRetry={query.refetch}
          />
        </Card>
      </>
    );
  }

  const report = query.data;
  const risks = [
    ...(report.sections.attack_types ?? []),
    ...(report.sections.general_risk_assessment ?? []),
  ];

  async function handleDelete() {
    try {
      await remove.mutateAsync(reportId);
      toast({ variant: "success", title: "Report deleted" });
      navigate("/reports", { replace: true });
    } catch (error) {
      toast({ variant: "error", title: "Delete failed", description: errorMessage(error) });
    }
  }

  return (
    <>
      <BackLink />

      <header className="mb-7">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0">
            <p className="eyebrow mb-2">Report</p>
            <h1 className="font-mono text-2xl font-semibold tracking-[-0.03em] text-ink">
              {report.report_name}
            </h1>
            <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-2">
              <StatusBadge status={report.status} />
              <IntegrityBadge state={report.integrity_state} />
              <ClassificationSelect
                reportId={report.report_id}
                value={report.classification}
              />
              <span className="text-[0.8125rem] text-ink-faint">
                {formatDateTime(report.generated_at)}
              </span>
              <Tooltip content={report.report_id}>
                <span className="ident text-xs">{shortId(report.report_id)}</span>
              </Tooltip>
            </div>
          </div>

          <div className="flex shrink-0 items-center gap-1">
            <ExportMenu
              download={(format) => exportReport.mutateAsync({ reportId, format })}
            />
            <ShareDialog report={report} />
            <Button
              variant="ghost"
              size="sm"
              loading={remove.isPending}
              onClick={handleDelete}
            >
              <Trash2 />
              Delete
            </Button>
          </div>
        </div>

        <div className="mt-6 grid gap-4 lg:grid-cols-[1.6fr_1fr]">
          <div className="rounded-lg border border-line bg-surface px-5 py-4">
            <p className="eyebrow mb-3">Severity profile</p>
            <SeveritySpine counts={severityCounts(risks)} height="h-2" showLegend />
          </div>
          <Integrity report={report} />
        </div>
      </header>

      {report.errors?.length > 0 && <SectionErrors errors={report.errors} />}

      <ReportBody report={report} />

      {/* Below the findings, not above them: the graph is a way to read the
          report, not a replacement for it. */}
      <GraphPanel reportId={reportId} />
    </>
  );
}

/**
 * File integrity for the source log.
 *
 * The sealed hash is shown in full rather than shortened: it is the evidence,
 * and an analyst comparing it against something else needs all of it.
 */
function Integrity({ report }) {
  const token = integrityToken(report.integrity_state);

  return (
    <div className={`rounded-lg border ${token.border} ${token.tint} px-5 py-4`}>
      <div className="flex items-center justify-between gap-3">
        <p className="eyebrow">Source integrity</p>
        <IntegrityBadge state={report.integrity_state} />
      </div>

      <p className="mt-2.5 text-[0.8125rem] leading-snug text-ink-dim">{token.description}</p>

      <dl className="mt-3 space-y-1.5 text-xs">
        <div className="flex gap-2">
          <dt className="shrink-0 text-ink-faint">Sealed hash</dt>
          <dd className="ident min-w-0 break-all text-ink-dim">
            {report.file_hash ?? "not recorded — the source file was unreadable"}
          </dd>
        </div>
        <div className="flex gap-2">
          <dt className="shrink-0 text-ink-faint">Last checked</dt>
          <dd className="text-ink-dim">
            {report.integrity_checked_at ? formatDateTime(report.integrity_checked_at) : "never"}
          </dd>
        </div>
      </dl>
    </div>
  );
}

function BackLink() {
  return (
    <Button variant="ghost" size="sm" className="-ml-3 mb-4" asChild>
      <Link to="/reports">
        <ArrowLeft />
        All reports
      </Link>
    </Button>
  );
}

/**
 * A section that failed twice is stored as a typed error rather than as an
 * empty section, so the report can say which part is missing and why. The
 * prototype merged failures into the report and they became indistinguishable
 * from sections that legitimately found nothing.
 */
function SectionErrors({ errors }) {
  return (
    <div className="mb-6 rounded-lg border border-medium/30 bg-medium/8 p-4">
      <div className="flex items-start gap-2.5">
        <AlertTriangle className="mt-0.5 size-4 shrink-0 text-medium" aria-hidden="true" />
        <div className="min-w-0 flex-1">
          <p className="font-mono text-[0.8125rem] font-medium text-medium">
            {errors.length} section{errors.length === 1 ? "" : "s"} could not be generated
          </p>
          <p className="mt-1 text-[0.8125rem] text-ink-dim">
            The rest of the report is complete. A missing section is not an empty one.
          </p>
          <Separator className="my-3 bg-medium/20" />
          <ul className="space-y-1.5">
            {errors.map((error, index) => (
              <li key={index} className="text-[0.8125rem] text-ink-dim">
                <span className="ident text-ink">{error.section}</span>{" "}
                <span className="text-ink-faint">({error.stage})</span> — {error.detail}
              </li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  );
}

function DetailSkeleton() {
  return (
    <>
      <Skeleton className="mb-6 h-4 w-24" />
      <Skeleton className="h-8 w-80" />
      <Skeleton className="mt-3 h-4 w-56" />
      <Skeleton className="mt-6 h-20 w-full rounded-lg" />
      <Card className="mt-6">
        <LoadingState label="Loading report" />
      </Card>
    </>
  );
}
