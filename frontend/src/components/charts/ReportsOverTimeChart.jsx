import { FileText } from "lucide-react";
import { useMemo } from "react";
import { Bar, BarChart, CartesianGrid, Tooltip, XAxis, YAxis } from "recharts";

import { ChartFrame, ChartTooltip } from "./ChartFrame";
import { AXIS, CURSOR_FILL, GRID, INK_FAINT, formatDay } from "./chart-theme";

/**
 * Report volume per day, split by outcome.
 *
 * The clean bar is graphite; only the "needs attention" segment is coloured,
 * because a partial or failed report is a state an analyst has to act on. The
 * server returns a bucket for every day in the window, including zeros — the
 * gaps are real gaps, not a compressed axis.
 */
export function ReportsOverTimeChart({ query, days, actions }) {
  const data = useMemo(
    () => (query.data ?? []).map((bucket) => ({ ...bucket, clean: bucket.total - bucket.attention })),
    [query.data],
  );

  return (
    <ChartFrame
      title="Reports generated"
      description={`Daily volume over the last ${days} days. Amber marks reports that came back partial or failed.`}
      query={query}
      isEmpty={(buckets) => buckets.every((bucket) => bucket.total === 0)}
      emptyIcon={FileText}
      emptyTitle="No reports in this window"
      emptyDescription="Generate a report, or widen the window, to see volume over time."
      actions={actions}
      height={230}
    >
      {() => (
        <BarChart data={data} margin={{ top: 4, right: 4, bottom: 0, left: -18 }} barCategoryGap="22%">
          <CartesianGrid {...GRID} />
          <XAxis
            dataKey="day"
            {...AXIS}
            tickFormatter={formatDay}
            interval="preserveStartEnd"
            minTickGap={26}
          />
          <YAxis {...AXIS} allowDecimals={false} width={40} />
          <Tooltip
            cursor={CURSOR_FILL}
            content={<ChartTooltip labelFormatter={formatDay} />}
          />
          <Bar dataKey="clean" name="Complete" stackId="reports" fill={INK_FAINT} radius={[0, 0, 0, 0]} />
          <Bar
            dataKey="attention"
            name="Needs attention"
            stackId="reports"
            fill="var(--color-medium)"
            radius={[2, 2, 0, 0]}
          />
        </BarChart>
      )}
    </ChartFrame>
  );
}
