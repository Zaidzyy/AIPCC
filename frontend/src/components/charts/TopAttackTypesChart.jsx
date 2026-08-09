import { Crosshair } from "lucide-react";
import { useMemo } from "react";
import { Bar, BarChart, LabelList, Tooltip, XAxis, YAxis } from "recharts";

import { ChartFrame, ChartTooltip } from "./ChartFrame";
import { AXIS, CURSOR_FILL, INK_DIM } from "./chart-theme";

/**
 * The most frequently observed techniques, with their MITRE mapping.
 *
 * Drawn in graphite: frequency is not severity, and colouring it would dilute
 * the rule that anything coloured in this UI is telling the analyst something.
 * The MITRE id rides on the axis label because "T1110" is what an analyst
 * actually searches for.
 */
export function TopAttackTypesChart({ query }) {
  const data = useMemo(
    () =>
      (query.data ?? []).map((row) => ({
        ...row,
        label: truncate(row.attack_name),
        full: row.attack_mitre_technique_id
          ? `${row.attack_mitre_technique_id} · ${row.attack_name}`
          : row.attack_name,
      })),
    [query.data],
  );

  return (
    <ChartFrame
      title="Top attack types"
      description="How often each technique was identified across your reports."
      query={query}
      isEmpty={(rows) => rows.length === 0}
      emptyIcon={Crosshair}
      emptyTitle="No attacks identified yet"
      emptyDescription="Techniques appear here once a report's attack-types section has run."
      height={290}
    >
      {() => (
        <BarChart
          data={data}
          layout="vertical"
          margin={{ top: 4, right: 34, bottom: 4, left: 4 }}
          barCategoryGap="30%"
        >
          <XAxis type="number" hide allowDecimals={false} />
          <YAxis
            type="category"
            dataKey="label"
            {...AXIS}
            width={186}
            tick={{ ...AXIS.tick, fontSize: 10.5 }}
          />
          <Tooltip
            cursor={CURSOR_FILL}
            // The axis had to truncate; the tooltip shows the technique in
            // full, MITRE id first, which is what an analyst searches on.
            content={
              <ChartTooltip
                labelFormatter={(label, payload) => payload?.[0]?.payload?.full ?? label}
              />
            }
          />
          <Bar dataKey="count" name="Occurrences" fill={INK_DIM} radius={[0, 3, 3, 0]} maxBarSize={18}>
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

/**
 * Recharts word-wraps a tick that does not fit its axis width, which is fine
 * for two lines and unreadable at three. The cap keeps every label inside two.
 */
function truncate(value, max = 34) {
  const name = String(value ?? "");
  return name.length > max ? `${name.slice(0, max - 1)}…` : name;
}
