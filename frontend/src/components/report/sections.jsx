import { CircleDashed } from "lucide-react";

import {
  Badge,
  SeverityBadge,
  TBody,
  TD,
  TH,
  THead,
  TR,
  Table,
} from "@/components/ui";
import { orDash, severityToken } from "@/lib/format";
import { cn } from "@/lib/utils";

/**
 * The five report sections.
 *
 * Field names come straight from `app/schemas/report.py` — the canonical
 * schema — so a rename on the backend shows up here as a blank cell rather
 * than as a silently wrong value. Every field is nullable by design: the
 * prompts instruct the model to emit null rather than invent a CVE, so `—`
 * is a legitimate value throughout, not a rendering failure.
 */

export function SectionEmpty({ label }) {
  return (
    <div className="flex items-center gap-2.5 px-5 py-8 text-sm text-ink-faint">
      <CircleDashed className="size-4" aria-hidden="true" />
      No {label} were identified in this log.
    </div>
  );
}

/** A row's left rule, coloured by its severity — the spine, per item. */
function severityRule(level) {
  return cn("border-l-2 pl-4", severityToken(level).rule);
}

export function AttackTypes({ items }) {
  if (!items?.length) return <SectionEmpty label="attack types" />;

  return (
    <ul className="divide-y divide-line/70">
      {items.map((attack, index) => (
        <li key={index} className="px-5 py-5">
          <div className={severityRule(attack.risk_level)}>
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="min-w-0">
                <h3 className="font-mono text-[0.9375rem] font-semibold text-ink">
                  {orDash(attack.attack_name)}
                </h3>
                {attack.attack_mitre_technique_id && (
                  <div className="mt-1.5 flex flex-wrap items-center gap-2">
                    <Badge>{attack.attack_mitre_technique_id}</Badge>
                    <span className="text-[0.8125rem] text-ink-faint">
                      {orDash(attack.attack_mitre_technique_name)}
                    </span>
                  </div>
                )}
              </div>
              <SeverityBadge level={attack.risk_level} />
            </div>

            {attack.attack_description && (
              <p className="mt-3 max-w-3xl text-sm leading-relaxed text-ink-dim">
                {attack.attack_description}
              </p>
            )}

            <dl className="mt-4 grid gap-x-8 gap-y-3 sm:grid-cols-2">
              <Detail label="Risk" value={attack.risk_name} />
              <Detail label="Likelihood" value={attack.likelihood} />
              <Detail label="Impact" value={attack.impact} className="sm:col-span-2" />
              <Detail label="Mitigation" value={attack.mitigation} className="sm:col-span-2" />
            </dl>
          </div>
        </li>
      ))}
    </ul>
  );
}

export function RiskAssessment({ items }) {
  if (!items?.length) return <SectionEmpty label="general risks" />;

  return (
    <Table>
      <THead>
        <TR className="hover:bg-transparent">
          <TH>Risk</TH>
          <TH className="w-28">Level</TH>
          <TH className="hidden w-28 sm:table-cell">Likelihood</TH>
          <TH className="hidden lg:table-cell">Mitigation</TH>
        </TR>
      </THead>
      <TBody>
        {items.map((risk, index) => (
          <TR key={index}>
            <TD>
              <p className="font-medium text-ink">{orDash(risk.risk_name)}</p>
              {risk.risk_description && (
                <p className="mt-1 max-w-lg text-[0.8125rem] leading-relaxed">
                  {risk.risk_description}
                </p>
              )}
              {risk.impact && (
                <p className="mt-1.5 text-[0.8125rem] text-ink-faint">
                  <span className="eyebrow mr-1.5">Impact</span>
                  {risk.impact}
                </p>
              )}
            </TD>
            <TD>
              <SeverityBadge level={risk.risk_level} />
            </TD>
            <TD className="hidden sm:table-cell">{orDash(risk.likelihood)}</TD>
            <TD className="hidden max-w-sm text-[0.8125rem] lg:table-cell">
              {orDash(risk.mitigation)}
            </TD>
          </TR>
        ))}
      </TBody>
    </Table>
  );
}

export function Vulnerabilities({ items }) {
  if (!items?.length) return <SectionEmpty label="vulnerabilities" />;

  return (
    <ul className="divide-y divide-line/70">
      {items.map((vulnerability, index) => (
        <li key={index} className="px-5 py-5">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <h3 className="font-mono text-[0.9375rem] font-semibold text-ink">
              {orDash(vulnerability.vulnerability_name)}
            </h3>
            <div className="flex flex-wrap items-center gap-2">
              {/* Null when the model could not identify a real identifier —
                  it is instructed never to invent one. */}
              {vulnerability.cve_id && <Badge>{vulnerability.cve_id}</Badge>}
              {vulnerability.cwe_id && <Badge variant="outline">{vulnerability.cwe_id}</Badge>}
            </div>
          </div>

          {vulnerability.vulnerability_description && (
            <p className="mt-3 max-w-3xl text-sm leading-relaxed text-ink-dim">
              {vulnerability.vulnerability_description}
            </p>
          )}

          <dl className="mt-4 grid gap-x-8 gap-y-3">
            <Detail label={vulnerability.cve_id ?? "CVE"} value={vulnerability.cve_description} />
            <Detail label={vulnerability.cwe_id ?? "CWE"} value={vulnerability.cwe_description} />
          </dl>
        </li>
      ))}
    </ul>
  );
}

export function Anomalies({ items }) {
  if (!items?.length) return <SectionEmpty label="anomalies" />;

  return (
    <Table>
      <THead>
        <TR className="hover:bg-transparent">
          <TH>Anomaly</TH>
          <TH className="hidden md:table-cell">Principal</TH>
          <TH className="hidden lg:table-cell">Source → Destination</TH>
          <TH className="hidden sm:table-cell">Protocol</TH>
          <TH className="w-20 text-right">Count</TH>
        </TR>
      </THead>
      <TBody>
        {items.map((anomaly, index) => (
          <TR key={index}>
            <TD>
              <p className="font-medium text-ink">{orDash(anomaly.anomaly_name)}</p>
              {(anomaly.first_occurrence || anomaly.last_occurrence) && (
                <p className="ident mt-1 text-xs">
                  {orDash(anomaly.first_occurrence)} → {orDash(anomaly.last_occurrence)}
                </p>
              )}
            </TD>
            <TD className="hidden md:table-cell">
              <span className="text-ink">{orDash(anomaly.user_name)}</span>
              {anomaly.user_id && (
                <span className="ident ml-1.5 text-xs">{anomaly.user_id}</span>
              )}
            </TD>
            <TD className="ident hidden lg:table-cell">
              {orDash(anomaly.source_ip)} → {orDash(anomaly.destination_ip)}
            </TD>
            <TD className="hidden sm:table-cell">
              {anomaly.protocol ? <Badge variant="outline">{anomaly.protocol}</Badge> : "—"}
            </TD>
            <TD className="text-right font-mono tabular-nums text-ink">
              {anomaly.counted ?? "—"}
            </TD>
          </TR>
        ))}
      </TBody>
    </Table>
  );
}

export function Timeline({ items }) {
  if (!items?.length) return <SectionEmpty label="timeline events" />;

  return (
    <ol className="relative px-5 py-5">
      {/* The rail is the sequence: these events are ordered, so a connecting
          line encodes something true rather than decorating the list. */}
      <span
        className="absolute bottom-8 left-[1.4375rem] top-8 w-px bg-line"
        aria-hidden="true"
      />
      {items.map((event, index) => (
        <li key={index} className="relative flex gap-4 py-3">
          <span
            className="relative z-10 mt-1.5 size-2 shrink-0 rounded-full bg-ink-faint ring-4 ring-surface"
            aria-hidden="true"
          />
          <div className="min-w-0 flex-1">
            <p className="ident text-xs">{orDash(event.time_stamp)}</p>
            <p className="mt-0.5 text-sm font-medium text-ink">{orDash(event.event_name)}</p>
            <p className="mt-0.5 text-[0.8125rem] text-ink-dim">
              {orDash(event.entity)}
              {event.duration && (
                <>
                  <span className="mx-2 text-ink-faint">·</span>
                  {event.duration}
                </>
              )}
            </p>
          </div>
        </li>
      ))}
    </ol>
  );
}

function Detail({ label, value, className }) {
  if (!value) return null;
  return (
    <div className={className}>
      <dt className="eyebrow">{label}</dt>
      <dd className="mt-1 text-[0.8125rem] leading-relaxed text-ink-dim">{value}</dd>
    </div>
  );
}
