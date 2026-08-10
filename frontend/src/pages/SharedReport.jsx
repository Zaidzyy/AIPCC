import { Clock, Link2Off, ShieldAlert, ShieldX } from "lucide-react";
import { useParams } from "react-router-dom";

import { SeveritySpine } from "@/components/common/SeveritySpine";
import { ClassificationIcon } from "@/components/report/ClassificationSelect";
import { ExportMenu } from "@/components/report/ExportMenu";
import { ReportBody } from "@/components/report/ReportBody";
import { Card, IntegrityBadge, LoadingState, StatusBadge } from "@/components/ui";
import { useExportSharedReport, useSharedReport } from "@/hooks/queries";
import { formatDateTime, formatRelative, severityCounts } from "@/lib/format";

/**
 * The public read-only view of one shared report.
 *
 * It lives outside `ProtectedRoute` and outside `AppShell` — no sidebar, no
 * topbar, no navigation of any kind. That is not a styling choice: the shell
 * exists to move between a user's reports, and there is nothing here for a
 * link holder to move to. A shell with every link removed would still be a
 * shell with a "Dashboard" item one CSS rule away from coming back.
 *
 * Nothing on this page identifies the owner. The API does not send it — see
 * `schemas/share.py` — so there is nothing here to leave out by accident.
 */
export function SharedReport() {
  const { token } = useParams();
  const query = useSharedReport(token);
  const exportShared = useExportSharedReport();

  return (
    <div className="min-h-dvh bg-void">
      <header className="border-b border-line">
        <div className="mx-auto flex max-w-5xl items-center justify-between gap-4 px-5 py-3.5">
          <div className="flex items-baseline gap-2.5">
            <span className="font-mono text-sm font-semibold tracking-tight text-ink">AIPCC</span>
            <span className="hidden text-xs text-ink-faint sm:inline">
              Shared security report
            </span>
          </div>
          {query.isSuccess && (
            <ExportMenu
              download={(format) => exportShared.mutateAsync({ token, format })}
            />
          )}
        </div>
      </header>

      <main className="mx-auto max-w-5xl px-5 py-8">
        {query.isPending && (
          <Card>
            <LoadingState label="Opening shared report" />
          </Card>
        )}
        {query.isError && <LinkProblem error={query.error} />}
        {query.isSuccess && <SharedBody report={query.data} />}
      </main>

      <footer className="mx-auto max-w-5xl px-5 pb-10 pt-2">
        <p className="text-xs leading-relaxed text-ink-faint">
          This is a read-only copy shared by link. It shows one report and nothing else, and
          the link can be revoked at any time by whoever created it.
        </p>
      </footer>
    </div>
  );
}

function SharedBody({ report }) {
  const risks = [
    ...(report.sections.attack_types ?? []),
    ...(report.sections.general_risk_assessment ?? []),
  ];

  return (
    <>
      <header className="mb-7">
        <p className="eyebrow mb-2">Report</p>
        <h1 className="font-mono text-2xl font-semibold tracking-[-0.03em] text-ink">
          {report.report_name}
        </h1>

        <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-2">
          <StatusBadge status={report.status} />
          <IntegrityBadge state={report.integrity_state} />
          <span className="flex items-center gap-1.5 text-[0.8125rem] text-ink-dim">
            <ClassificationIcon level={report.classification} />
            {report.classification}
          </span>
          <span className="text-[0.8125rem] text-ink-faint">
            {formatDateTime(report.generated_at)}
          </span>
          {report.document_name && (
            <span className="ident text-xs">{report.document_name}</span>
          )}
        </div>

        <div className="mt-6 grid gap-4 lg:grid-cols-[1.6fr_1fr]">
          <div className="rounded-lg border border-line bg-surface px-5 py-4">
            <p className="eyebrow mb-3">Severity profile</p>
            <SeveritySpine counts={severityCounts(risks)} height="h-2" showLegend />
          </div>
          <div className="rounded-lg border border-line bg-surface px-5 py-4">
            <p className="eyebrow mb-3">This link</p>
            <p className="flex items-center gap-2 text-[0.8125rem] text-ink-dim">
              <Clock className="size-3.5 shrink-0 text-ink-faint" aria-hidden="true" />
              {report.expires_at
                ? `Expires ${formatRelative(report.expires_at)} — ${formatDateTime(report.expires_at)}`
                : "Does not expire"}
            </p>
          </div>
        </div>
      </header>

      <ReportBody report={report} />
    </>
  );
}

/**
 * Why a link stopped working, in the recipient's terms.
 *
 * The three server refusals are three different situations and the copy says
 * so. A single "something went wrong" would leave the reader unable to tell
 * whether to ask for a new link or to stop asking.
 */
const PROBLEMS = {
  404: {
    Icon: Link2Off,
    title: "This link is not valid",
    body: "It may have been revoked, or the address may have been mistyped. Ask whoever sent it for a new one.",
  },
  410: {
    Icon: Clock,
    title: "This link has expired",
    body: "Share links are given a time limit when they are created. Ask whoever sent it to issue a new one.",
  },
  403: {
    Icon: ShieldX,
    title: "This report is no longer available by link",
    body: "Its classification was raised after the link was created, so it can no longer be read outside the application.",
  },
};

function LinkProblem({ error }) {
  const status = error?.response?.status;
  const problem = PROBLEMS[status] ?? {
    Icon: ShieldAlert,
    title: "This report could not be opened",
    body: "The service did not answer. Try again in a moment.",
  };
  const { Icon, title, body } = problem;

  return (
    <Card className="px-6 py-12">
      <div className="mx-auto flex max-w-md flex-col items-center text-center">
        <Icon className="size-6 text-ink-faint" aria-hidden="true" />
        <h1 className="mt-4 font-mono text-base font-semibold text-ink">{title}</h1>
        <p className="mt-2 text-sm leading-relaxed text-ink-dim">{body}</p>
      </div>
    </Card>
  );
}
