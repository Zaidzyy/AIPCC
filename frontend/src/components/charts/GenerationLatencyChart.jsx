import { Timer } from "lucide-react";
import { CartesianGrid, Line, LineChart, Tooltip, XAxis, YAxis } from "recharts";

import { ChartFrame, ChartTooltip } from "./ChartFrame";
import { AXIS, CURSOR_LINE, GRID, INK_DIM, INK_FAINT, formatDay } from "./chart-theme";
import { formatDuration } from "@/lib/format";

/**
 * How long a report takes to generate, p50 against p95.
 *
 * Both lines, because the gap between them is the whole point: five sections
 * run concurrently, so the elapsed time is set by the slowest one, and a
 * median would report a system that feels faster than it is. p95 is what the
 * analyst waiting on a report actually experiences.
 *
 * p95 is drawn brighter than p50 — a value ordering, not a severity, so it
 * stays inside the monochrome ramp rather than reaching for a hue.
 */
export function GenerationLatencyChart({ query, days }) {
  return (
    <ChartFrame
      title="Generation latency"
      description={`p50 and p95 end-to-end report time over ${days} days. Reports stored without timing are excluded.`}
      query={query}
      isEmpty={(buckets) => buckets.every((bucket) => !bucket.reports)}
      emptyIcon={Timer}
      emptyTitle="Nothing timed yet"
      emptyDescription="Reports generated through the app record their wall-clock time here."
      height={230}
    >
      {(data) => (
        <LineChart data={data} margin={{ top: 4, right: 4, bottom: 0, left: -6 }}>
          <CartesianGrid {...GRID} />
          <XAxis
            dataKey="day"
            {...AXIS}
            tickFormatter={formatDay}
            interval="preserveStartEnd"
            minTickGap={26}
          />
          <YAxis {...AXIS} width={54} tickFormatter={formatDuration} />
          <Tooltip
            cursor={CURSOR_LINE}
            content={<ChartTooltip labelFormatter={formatDay} valueFormatter={formatDuration} />}
          />
          {/* Days with no reports are null and the line breaks there — joining
              across a gap would draw a trend through days that had none. */}
          <Line
            type="monotone"
            dataKey="p50_ms"
            name="p50"
            stroke={INK_FAINT}
            strokeWidth={1.5}
            dot={false}
            connectNulls={false}
          />
          <Line
            type="monotone"
            dataKey="p95_ms"
            name="p95"
            stroke={INK_DIM}
            strokeWidth={2}
            dot={false}
            connectNulls={false}
          />
        </LineChart>
      )}
    </ChartFrame>
  );
}
