import {
  Anomalies,
  AttackTypes,
  RiskAssessment,
  Timeline,
  Vulnerabilities,
} from "@/components/report/sections";
import { ThreatIntel } from "@/components/report/ThreatIntel";
import { Card, CardHeader, CardTitle } from "@/components/ui";
import { groupEvidence } from "@/lib/evidence";

/**
 * The body of a report — the five sections and its threat intelligence.
 *
 * Extracted so the authenticated Report Detail page and the public share view
 * render the same thing from the same code. Two renderings of one report would
 * be two places for a section to go missing, and the public one is the copy
 * nobody in the team ever looks at.
 *
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

export function ReportBody({ report }) {
  // Grouped once for the whole report rather than filtered per finding, which
  // would be O(findings x evidence) on a page that can hold sixty of each.
  // `null` when the response carries no evidence at all — the public share
  // view — and every disclosure disappears with it.
  const evidence = groupEvidence(report);

  return (
    <div className="space-y-6">
      {SECTIONS.map(({ key, label, Component }) => (
        <Card key={key} id={key} className="overflow-hidden scroll-mt-20">
          <CardHeader>
            <CardTitle>{label}</CardTitle>
            <span className="font-mono text-xs tabular-nums text-ink-faint">
              {report.sections[key]?.length ?? 0}
            </span>
          </CardHeader>
          <Component items={report.sections[key]} evidence={evidence} />
        </Card>
      ))}

      <Card id="threat_intel" className="overflow-hidden scroll-mt-20">
        <CardHeader>
          <CardTitle>Threat intelligence</CardTitle>
          <span className="font-mono text-xs tabular-nums text-ink-faint">
            {report.threat_intel?.length ?? 0}
          </span>
        </CardHeader>
        <ThreatIntel items={report.threat_intel} />
      </Card>
    </div>
  );
}
