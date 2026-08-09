import { AlertTriangle, ArrowLeft, Trash2 } from "lucide-react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { SeveritySpine } from "@/components/common/SeveritySpine";
import {
  Anomalies,
  AttackTypes,
  RiskAssessment,
  Timeline,
  Vulnerabilities,
} from "@/components/report/sections";
import {
  Badge,
  Button,
  Card,
  CardHeader,
  CardTitle,
  ErrorState,
  LoadingState,
  Separator,
  Skeleton,
  StatusBadge,
  Tooltip,
  useToast,
} from "@/components/ui";
import { useDeleteReport, useReport } from "@/hooks/queries";
import { errorMessage } from "@/lib/apiClient";
import { formatDateTime, severityCounts, shortId } from "@/lib/format";

/**
 * Section order matches the order the backend generates them in, which is also
 * the order an analyst reads them: what happened, how bad, what is weak, what
 * looks odd, and when.
 */
const SECTIONS = [
  { key: "attack_types", label: "Attack types", Component: AttackTypes },
  { key: "general_risk_assessment", label: "Risk assessment", Component: RiskAssessment },
  { key: "vulnerabilities", label: "Vulnerabilities", Component: Vulnerabilities },
  { key: "anomalies", label: "Anomalies", Component: Anomalies },
  { key: "timeline", label: "Timeline", Component: Timeline },
];

export function ReportDetail() {
  const { reportId } = useParams();
  const navigate = useNavigate();
  const { toast } = useToast();

  const query = useReport(reportId);
  const remove = useDeleteReport();

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
              <Badge variant="outline">{report.classification}</Badge>
              <span className="text-[0.8125rem] text-ink-faint">
                {formatDateTime(report.generated_at)}
              </span>
              <Tooltip content={report.report_id}>
                <span className="ident text-xs">{shortId(report.report_id)}</span>
              </Tooltip>
            </div>
          </div>

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

        <div className="mt-6 rounded-lg border border-line bg-surface px-5 py-4">
          <p className="eyebrow mb-3">Severity profile</p>
          <SeveritySpine counts={severityCounts(risks)} height="h-2" showLegend />
        </div>
      </header>

      {report.errors?.length > 0 && <SectionErrors errors={report.errors} />}

      <div className="space-y-6">
        {SECTIONS.map(({ key, label, Component }) => (
          <Card key={key} id={key} className="overflow-hidden scroll-mt-20">
            <CardHeader>
              <CardTitle>{label}</CardTitle>
              <span className="font-mono text-xs tabular-nums text-ink-faint">
                {report.sections[key]?.length ?? 0}
              </span>
            </CardHeader>
            <Component items={report.sections[key]} />
          </Card>
        ))}
      </div>
    </>
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
