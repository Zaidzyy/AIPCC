import { CircleCheck, CircleX, FlaskConical, TriangleAlert } from "lucide-react";

import { PageHeader } from "@/components/common/PageHeader";
import {
  Badge,
  Card,
  CardBody,
  CardHeader,
  CardTitle,
  EmptyState,
  ErrorState,
  Skeleton,
  TBody,
  TD,
  TH,
  THead,
  TR,
  Table,
  Tooltip,
} from "@/components/ui";
import { useEvaluation } from "@/hooks/queries";
import { formatDateTime, formatDuration, formatTokens, formatUsd } from "@/lib/format";

/**
 * What the last evaluation run said.
 *
 * Reads the committed result of `python -m app.eval.run`; it does not run one.
 * A live evaluation costs money and takes half a minute, so an endpoint that
 * triggered it would be a bill with a refresh button.
 *
 * The mode banner is the most important thing on this page. A replayed number
 * describes frozen fixtures and the harness that scores them; only a live run
 * describes a model. Presenting them identically is the main way a harness
 * like this ends up lying, so they are never presented identically.
 */
export function Evaluation() {
  const query = useEvaluation();

  if (query.isError) {
    const missing = query.error?.response?.status === 404;
    return (
      <>
        <Header />
        <Card>
          {missing ? (
            // "Nobody has run this" is not "it scored zero", so it does not
            // render as a page of zeros.
            <EmptyState
              icon={FlaskConical}
              title="No evaluation has been run yet"
              description="Run `python -m app.eval.run` in backend/ and commit app/eval/results/latest.json. See backend/EVAL.md."
            />
          ) : (
            <ErrorState
              error={query.error}
              title="Could not load the evaluation"
              onRetry={query.refetch}
            />
          )}
        </Card>
      </>
    );
  }

  if (query.isPending) {
    return (
      <>
        <Header />
        <Card>
          <CardBody className="space-y-3">
            <Skeleton className="h-8 w-1/3" />
            <Skeleton className="h-40 w-full" />
          </CardBody>
        </Card>
      </>
    );
  }

  const { run, metrics, catalogues, gate, attacks, anomalies } = query.data;
  const replayed = run.mode === "replay";

  return (
    <>
      <Header />

      <div
        className={`mb-6 flex flex-wrap items-start gap-3 rounded-lg border px-5 py-4 ${
          gate?.passed === false ? "border-critical/35 bg-critical/10" : "border-line bg-surface"
        }`}
      >
        {gate?.passed === false ? (
          <CircleX className="mt-0.5 size-4 shrink-0 text-critical" aria-hidden="true" />
        ) : (
          <CircleCheck className="mt-0.5 size-4 shrink-0 text-ok" aria-hidden="true" />
        )}
        <div className="min-w-0 flex-1">
          <p className="text-sm text-ink">
            {gate?.passed === false
              ? "The quality gate is failing."
              : "The quality gate passed."}{" "}
            <span className="text-ink-dim">
              Run {formatDateTime(run.at)} against {run.golden_log} ({run.golden_chunks} chunks),
              ATT&amp;CK v{catalogues.mitre_attack.version}, CWE v{catalogues.cwe.version}.
            </span>
          </p>
          {gate?.breaches?.length > 0 && (
            <ul className="mt-2 space-y-1">
              {gate.breaches.map((breach) => (
                <li key={breach} className="text-[0.8125rem] text-critical">
                  {breach}
                </li>
              ))}
            </ul>
          )}
        </div>
        <Tooltip
          content={
            replayed
              ? "Replayed from responses recorded once from a real provider. This measures the harness, not the current model."
              : "Live call to the configured provider. These numbers describe a model."
          }
        >
          <Badge variant={replayed ? "outline" : "neutral"}>
            {replayed ? "replayed" : "live"} · {run.provider}
          </Badge>
        </Tooltip>
      </div>

      {replayed && (
        // The icon and the prose are separate flex items; the prose is one
        // block. Putting `flex` on the paragraph itself made every inline
        // <span> a flex item and broke the sentence into columns.
        <div className="mb-6 flex items-start gap-2">
          <TriangleAlert
            className="mt-0.5 size-3.5 shrink-0 text-ink-faint"
            aria-hidden="true"
          />
          <p className="max-w-4xl text-[0.8125rem] leading-relaxed text-ink-faint">
            These figures come from responses recorded once from{" "}
            <span className="ident">{run.recorded_from}</span> and replayed deterministically.
            They show that the validators, the citation resolver and the thresholds work — not
            how the current model performs. Run{" "}
            <span className="ident">app.eval.run --live</span> for that.
          </p>
        </div>
      )}

      <div className="mb-6 grid gap-px overflow-hidden rounded-lg border border-line bg-line/60 sm:grid-cols-2 xl:grid-cols-4">
        <Metric
          label="Hallucination rate"
          value={pct(metrics.hallucination_rate)}
          detail={`${metrics.invalid_identifiers}/${metrics.identifiers_emitted} identifiers invalid`}
          good={metrics.hallucination_rate === 0}
        />
        <Metric
          label="Grounding rate"
          value={pct(metrics.grounding_rate)}
          detail={`${metrics.findings_grounded}/${metrics.findings_total} findings cite real content`}
          good={metrics.grounding_rate === 1}
        />
        <Metric
          label="Recall"
          value={pct(metrics.recall)}
          detail={`${metrics.matched_total}/${metrics.expected_total} labels — ${pct(
            metrics.distinct_recall,
          )} with a finding of their own`}
        />
        <Metric
          label="Precision"
          value={pct(metrics.precision)}
          detail={`${metrics.false_positives} benign events reported as attacks`}
          good={metrics.false_positives === 0}
        />
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Identifier checks</CardTitle>
          </CardHeader>
          {Object.keys(metrics.issues_by_kind ?? {}).length === 0 ? (
            <EmptyState
              icon={CircleCheck}
              title="No identifier issues"
              description={`Every MITRE technique, CVE and CWE emitted (${metrics.identifiers_emitted}) checked out against the vendored catalogues.`}
            />
          ) : (
            <Table>
              <THead>
                <TR className="hover:bg-transparent">
                  <TH>Kind</TH>
                  <TH className="w-20 text-right">Count</TH>
                </TR>
              </THead>
              <TBody>
                {Object.entries(metrics.issues_by_kind).map(([kind, count]) => (
                  <TR key={kind}>
                    <TD>
                      <span className="ident text-[0.8125rem]">{kind}</span>
                      <p className="mt-0.5 text-xs text-ink-faint">{ISSUE_HELP[kind] ?? ""}</p>
                    </TD>
                    <TD className="text-right font-mono tabular-nums">{count}</TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          )}
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Run</CardTitle>
          </CardHeader>
          <CardBody>
            <dl className="grid grid-cols-2 gap-x-6 gap-y-3">
              <Row label="Sections" value={`${metrics.sections_succeeded}/${metrics.sections_total}`} />
              <Row label="Retry rate" value={pct(metrics.retry_rate)} />
              <Row label="LLM calls" value={metrics.llm_calls} />
              <Row label="Fabricated citations" value={metrics.invalid_citations} />
              <Row label="Tokens" value={formatTokens(metrics.total_tokens)} />
              <Row label="Cost" value={formatUsd(metrics.cost_usd)} />
              <Row label="Generation" value={formatDuration(metrics.generation_ms)} />
              <Row label="p95 call" value={formatDuration(metrics.p95_call_ms)} />
              <Row
                label="MITRE agreement"
                value={`${pct(metrics.mitre_agreement)} (${metrics.mitre_agreed}/${metrics.mitre_expected})`}
                hint="Reported, not enforced — several events map to more than one defensible technique."
                className="col-span-2"
              />
            </dl>
          </CardBody>
        </Card>
      </div>

      {(attacks?.missed?.length > 0 || anomalies?.missed?.length > 0) && (
        <Card className="mt-6">
          <CardHeader>
            <CardTitle>Missed by the model</CardTitle>
          </CardHeader>
          <CardBody>
            <div className="flex flex-wrap gap-2">
              {[...(attacks?.missed ?? []), ...(anomalies?.missed ?? [])].map((id) => (
                <Badge key={id} variant="outline">
                  {id}
                </Badge>
              ))}
            </div>
          </CardBody>
        </Card>
      )}
    </>
  );
}

const ISSUE_HELP = {
  mitre_unknown: "A technique id that does not exist in ATT&CK.",
  mitre_name_mismatch: "A real id under a name that is not its own.",
  mitre_malformed: "Not shaped like a technique id.",
  mitre_retired: "Real, but deprecated or revoked — not counted as a hallucination.",
  cve_malformed: "Not shaped like CVE-YYYY-NNNN.",
  cwe_unknown: "A weakness id that does not exist in the CWE catalogue.",
  cwe_malformed: "Not shaped like CWE-NNN.",
};

function Header() {
  return (
    <PageHeader
      eyebrow="Analysis"
      title="Evaluation"
      description="How the report generator scores against a hand-labelled log and the published MITRE ATT&CK and CWE catalogues. Run with `python -m app.eval.run`; see backend/EVAL.md."
    />
  );
}

/** `null` renders as `—`. A rate with no denominator is not zero. */
function pct(value) {
  if (value === null || value === undefined) return "—";
  return `${(value * 100).toFixed(1)}%`;
}

function Metric({ label, value, detail, good }) {
  return (
    <div className="bg-surface/70 px-5 py-5">
      <p className="eyebrow">{label}</p>
      <p
        className={`mt-1.5 font-mono text-3xl font-semibold tabular-nums tracking-tight ${
          good ? "text-ok" : "text-ink"
        }`}
      >
        {value}
      </p>
      <p className="mt-1 text-[0.8125rem] text-ink-faint">{detail}</p>
    </div>
  );
}

function Row({ label, value, hint, className }) {
  return (
    <div className={className}>
      <dt className="eyebrow">{label}</dt>
      <dd className="mt-0.5 font-mono text-sm tabular-nums text-ink">{value}</dd>
      {hint && <p className="mt-0.5 text-xs text-ink-faint">{hint}</p>}
    </div>
  );
}
