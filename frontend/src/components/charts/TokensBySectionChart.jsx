import { Layers } from "lucide-react";
import { useMemo } from "react";
import { Bar, BarChart, CartesianGrid, Tooltip, XAxis, YAxis } from "recharts";

import { ChartFrame, ChartTooltip } from "./ChartFrame";
import { AXIS, CURSOR_FILL, GRID, INK_DIM, INK_FAINT, formatCount } from "./chart-theme";

const LABELS = {
  attack_types: "Attacks",
  general_risk_assessment: "Risks",
  vulnerabilities: "Vulns",
  anomalies: "Anomalies",
  timeline: "Timeline",
  chat: "Chat",
};

/**
 * Where the tokens go.
 *
 * Split prompt from completion, because they are priced differently — usually
 * by an order of magnitude — so a section that is cheap to ask and expensive to
 * answer looks nothing like one that is the reverse, and a single "total" bar
 * would hide exactly that.
 *
 * Horizontal, because the categories are words. A vertical bar chart with six
 * section names on the x-axis either truncates them or rotates them 45°.
 */
export function TokensBySectionChart({ query }) {
  const data = useMemo(
    () =>
      (query.data ?? []).map((row) => ({
        ...row,
        label: LABELS[row.section] ?? row.section,
      })),
    [query.data],
  );

  return (
    <ChartFrame
      title="Tokens by section"
      description="Prompt and completion tokens per report section, plus chat. Ordered by total."
      query={query}
      isEmpty={(rows) => rows.length === 0}
      emptyIcon={Layers}
      emptyTitle="Nothing measured yet"
      emptyDescription="Token counts appear once a report has been generated through the app."
      height={230}
    >
      {() => (
        <BarChart
          data={data}
          layout="vertical"
          margin={{ top: 4, right: 8, bottom: 0, left: 8 }}
          barCategoryGap="26%"
        >
          <CartesianGrid {...GRID} horizontal={false} vertical />
          <XAxis type="number" {...AXIS} tickFormatter={formatCount} />
          <YAxis type="category" dataKey="label" {...AXIS} width={72} />
          <Tooltip cursor={CURSOR_FILL} content={<ChartTooltip valueFormatter={formatCount} />} />
          <Bar dataKey="prompt_tokens" name="Prompt" stackId="tokens" fill={INK_FAINT} />
          <Bar
            dataKey="completion_tokens"
            name="Completion"
            stackId="tokens"
            fill={INK_DIM}
            radius={[0, 2, 2, 0]}
          />
        </BarChart>
      )}
    </ChartFrame>
  );
}
