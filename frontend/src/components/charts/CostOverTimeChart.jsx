import { Coins } from "lucide-react";
import { Area, AreaChart, CartesianGrid, Tooltip, XAxis, YAxis } from "recharts";

import { ChartFrame, ChartTooltip } from "./ChartFrame";
import { AXIS, CURSOR_LINE, GRID, INK_FAINT, formatDay } from "./chart-theme";
import { formatUsd } from "@/lib/format";

/**
 * What the LLM cost, per day.
 *
 * Graphite, not chroma. Under this app's colour rule spend is not a severity
 * and not a state — a higher area already says "more", and giving money a hue
 * would dilute the hues that mean an analyst has to act. The one thing that
 * *would* earn colour here is an unpriced call, and that is surfaced as a
 * number in the panel beside this rather than as a stripe nobody can read.
 */
export function CostOverTimeChart({ query, days, actions }) {
  return (
    <ChartFrame
      title="LLM cost"
      description={`Daily spend over the last ${days} days, priced from the model table in config.`}
      query={query}
      isEmpty={(buckets) => buckets.every((bucket) => !bucket.calls)}
      emptyIcon={Coins}
      emptyTitle="No LLM calls in this window"
      emptyDescription="Generate a report and its token spend is recorded per call, per section."
      actions={actions}
      height={230}
    >
      {(data) => (
        <AreaChart data={data} margin={{ top: 4, right: 4, bottom: 0, left: -8 }}>
          <defs>
            <linearGradient id="cost-fill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={INK_FAINT} stopOpacity={0.35} />
              <stop offset="100%" stopColor={INK_FAINT} stopOpacity={0.02} />
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
          <YAxis {...AXIS} width={58} tickFormatter={formatUsd} />
          <Tooltip
            cursor={CURSOR_LINE}
            content={<ChartTooltip labelFormatter={formatDay} valueFormatter={formatUsd} />}
          />
          <Area
            type="monotone"
            dataKey="cost_usd"
            name="Cost"
            stroke={INK_FAINT}
            strokeWidth={1.5}
            fill="url(#cost-fill)"
            // A day whose provider reported no usage is null, not zero, and the
            // line must break rather than draw a dip to the axis that says the
            // day was free.
            connectNulls={false}
          />
        </AreaChart>
      )}
    </ChartFrame>
  );
}
