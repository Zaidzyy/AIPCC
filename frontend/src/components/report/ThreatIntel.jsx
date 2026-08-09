import { Globe, Hash, Network } from "lucide-react";

import { Badge, EmptyState, SeverityBadge, Table, TBody, TD, TH, THead, TR } from "@/components/ui";
import { orDash } from "@/lib/format";

const ICONS = { ip: Network, domain: Globe, hash: Hash };

/**
 * Threat-intel enrichment attached to a report by the n8n orchestrator:
 * AbuseIPDB reputation for the IPs its indicator pass found, VirusTotal for
 * file hashes, and its own IOC classification.
 *
 * The reputation score is shown as a number *and* a bar. The number is what an
 * analyst quotes in a ticket; the bar is what lets them scan twenty rows and
 * see which one is the problem.
 */
export function ThreatIntel({ items }) {
  if (!items?.length) {
    return (
      <EmptyState
        icon={Network}
        title="No enrichment for this report"
        description="Threat intelligence is added by the n8n orchestrator. Reports generated in the app do not carry it."
      />
    );
  }

  return (
    <Table>
      <THead>
        <TR>
          <TH>Indicator</TH>
          <TH>Classification</TH>
          <TH>Reputation</TH>
          <TH>Risk</TH>
          <TH>Source</TH>
        </TR>
      </THead>
      <TBody>
        {items.map((item) => {
          const Icon = ICONS[item.indicator_type] ?? Network;
          return (
            <TR key={item.id}>
              <TD>
                <span className="flex items-center gap-2">
                  <Icon className="size-3.5 shrink-0 text-ink-faint" aria-hidden="true" />
                  <span className="ident break-all">{item.indicator}</span>
                </span>
                {(item.country || item.usage_type) && (
                  <span className="mt-1 block text-xs text-ink-faint">
                    {[item.country, item.usage_type].filter(Boolean).join(" · ")}
                  </span>
                )}
              </TD>
              <TD className="text-ink-dim">{orDash(item.category)}</TD>
              <TD>
                <ReputationBar score={item.reputation_score} />
              </TD>
              <TD>
                <SeverityBadge level={item.risk_level} />
              </TD>
              <TD>
                <Badge variant="outline">{item.source}</Badge>
              </TD>
            </TR>
          );
        })}
      </TBody>
    </Table>
  );
}

/**
 * A provider that returned no score is not a provider that returned zero — a
 * domain AbuseIPDB has never been asked about must not read as "clean".
 */
function ReputationBar({ score }) {
  if (score === null || score === undefined) {
    return <span className="text-ink-faint">—</span>;
  }

  const clamped = Math.max(0, Math.min(100, Number(score) || 0));
  const tone =
    clamped >= 75 ? "bg-critical" : clamped >= 50 ? "bg-high" : clamped >= 25 ? "bg-medium" : "bg-low";

  return (
    <span className="flex items-center gap-2">
      <span className="font-mono text-xs tabular-nums text-ink">{clamped}</span>
      <span className="h-1 w-16 overflow-hidden rounded-full bg-raised">
        <span className={`block h-full ${tone}`} style={{ width: `${clamped}%` }} />
      </span>
    </span>
  );
}
