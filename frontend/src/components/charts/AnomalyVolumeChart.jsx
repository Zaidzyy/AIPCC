import { Activity } from "lucide-react";
import { Area, AreaChart, CartesianGrid, Tooltip, XAxis, YAxis } from "recharts";

import { ChartFrame, ChartTooltip } from "./ChartFrame";
import { AXIS, CURSOR_LINE, GRID, INK_DIM, formatCount, formatDay } from "./chart-theme";

/**
 * Anomaly volume per day.
 *
 * The area is `events` — the summed occurrence count the model attached to
 * each anomaly — because that is the number that spikes when something is
 * wrong. `findings`, the count of distinct anomalies, rides in the tooltip:
 * one anomaly seen four thousand times and four thousand separate anomalies
 * are very different days, and the chart should not conflate them.
 *
 * Graphite, not chroma: volume is not a severity.
 */
export function AnomalyVolumeChart({ query, days, actions }) {
  return (
    <ChartFrame
      title="Anomaly volume"
      description={`Occurrences recorded per day over the last ${days} days.`}
      query={query}
      isEmpty={(buckets) => buckets.every((bucket) => bucket.findings === 0)}
      emptyIcon={Activity}
      emptyTitle="No anomalies in this window"
      emptyDescription="Anomalies appear here once a report's anomaly section has run."
      actions={actions}
      height={230}
    >
      {(data) => (
        <AreaChart data={data} margin={{ top: 4, right: 4, bottom: 0, left: -12 }}>
          <defs>
            <linearGradient id="anomaly-fill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={INK_DIM} stopOpacity={0.32} />
              <stop offset="100%" stopColor={INK_DIM} stopOpacity={0.02} />
            </linearGradient>
          </defs>
          <CartesianGrid {...GRID} />
          <XAxis
            dataKey="day"
            {...AXIS}
            tickFormatter={formatDay}
            interval="preserveStartEnd"
            minTickGap={26}
          />
          <YAxis {...AXIS} width={44} tickFormatter={formatCount} allowDecimals={false} />
          <Tooltip
            cursor={CURSOR_LINE}
            content={<ChartTooltip labelFormatter={formatDay} />}
          />
          {/* Rendered under `events` so the tooltip lists distinct anomalies
              first; its stroke is transparent — it is a tooltip series, not a
              second line competing for the same vertical space. */}
          <Area
            dataKey="findings"
            name="Distinct anomalies"
            stroke="none"
            fill="none"
            activeDot={false}
            isAnimationActive={false}
          />
          <Area
            dataKey="events"
            name="Occurrences"
            stroke={INK_DIM}
            strokeWidth={1.5}
            fill="url(#anomaly-fill)"
            activeDot={{ r: 3, fill: "var(--color-ink)", stroke: "none" }}
          />
        </AreaChart>
      )}
    </ChartFrame>
  );
}
