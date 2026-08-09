import { ShieldAlert } from "lucide-react";
import { useMemo } from "react";
import { Bar, BarChart, Cell, LabelList, Tooltip, XAxis, YAxis } from "recharts";

import { ChartFrame, ChartTooltip } from "./ChartFrame";
import { AXIS, CURSOR_FILL, SEVERITY_COLOR, SEVERITY_LABEL } from "./chart-theme";

/**
 * Findings by severity, across attack risks and general risks together.
 *
 * Ranked horizontal bars rather than a pie: severity is ordinal, and a reader
 * comparing "how much critical versus how much high" reads lengths far more
 * accurately than angles. Severity is normalised server-side, so "Sev 1",
 * "CRITICAL " and "critical" arrive here as one bucket.
 */
export function SeverityChart({ query }) {
  const data = useMemo(
    () =>
      [...(query.data ?? [])]
        .reverse() // server sends low → critical; read top-down worst-first
        .map((slice) => ({ ...slice, label: SEVERITY_LABEL[slice.severity] ?? slice.severity })),
    [query.data],
  );

  return (
    <ChartFrame
      title="Findings by severity"
      description="Attack risks and general risk assessments, normalised to one ladder."
      query={query}
      isEmpty={(slices) => slices.every((slice) => slice.count === 0)}
      emptyIcon={ShieldAlert}
      emptyTitle="Nothing rated yet"
      emptyDescription="Severity appears once a report has produced risk findings."
      height={230}
    >
      {() => (
        <BarChart
          data={data}
          layout="vertical"
          margin={{ top: 4, right: 34, bottom: 4, left: 4 }}
          barCategoryGap="26%"
        >
          <XAxis type="number" hide allowDecimals={false} />
          <YAxis type="category" dataKey="label" {...AXIS} width={68} />
          <Tooltip cursor={CURSOR_FILL} content={<ChartTooltip />} />
          <Bar dataKey="count" name="Findings" radius={[0, 3, 3, 0]} maxBarSize={26}>
            {data.map((slice) => (
              <Cell key={slice.severity} fill={SEVERITY_COLOR[slice.severity]} />
            ))}
            <LabelList
              dataKey="count"
              position="right"
              className="fill-ink-dim"
              style={{ fontFamily: "var(--font-mono)", fontSize: 11 }}
            />
          </Bar>
        </BarChart>
      )}
    </ChartFrame>
  );
}
