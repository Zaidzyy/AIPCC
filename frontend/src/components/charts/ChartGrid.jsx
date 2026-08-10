import { AnomalyVolumeChart } from "./AnomalyVolumeChart";
import { CostOverTimeChart } from "./CostOverTimeChart";
import { GenerationLatencyChart } from "./GenerationLatencyChart";
import { ReportsOverTimeChart } from "./ReportsOverTimeChart";
import { SeverityChart } from "./SeverityChart";
import { TokensBySectionChart } from "./TokensBySectionChart";
import { TopAttackTypesChart } from "./TopAttackTypesChart";

/**
 * The dashboard charts, in one default-exported module.
 *
 * This exists to be `React.lazy`-ed. Recharts is ~400 kB of the bundle and
 * /dashboard is the landing route, so importing it eagerly puts the whole
 * charting library in front of the first paint. Behind a lazy boundary it
 * downloads in parallel with the aggregate requests it is waiting on anyway,
 * and the rest of the app — every route that draws no charts — never pays for
 * it at all.
 *
 * Nothing else in the app may import `recharts` directly, or the chunk merges
 * back into the entry bundle and this stops working. The Phase 9 cost charts
 * were added *here* for that reason rather than in a second lazy module: a
 * second boundary would download Recharts twice.
 */
export default function ChartGrid({ query, days, windowPicker }) {
  return (
    <>
      <ReportsOverTimeChart query={query.reportsOverTime} days={days} actions={windowPicker} />
      <SeverityChart query={query.severity} />
      <TopAttackTypesChart query={query.attacks} />
      <AnomalyVolumeChart query={query.anomalies} days={days} />
    </>
  );
}

/**
 * The cost panel's charts, kept in the same lazy chunk.
 *
 * Separated as an export rather than a module so the dashboard can place them
 * in their own section — "what this system found" and "what it cost to find
 * it" are two different questions and read badly interleaved.
 */
export function CostCharts({ query, days, windowPicker }) {
  return (
    <>
      <CostOverTimeChart query={query.cost} days={days} actions={windowPicker} />
      <TokensBySectionChart query={query.tokens} />
      <GenerationLatencyChart query={query.latency} days={days} />
    </>
  );
}
