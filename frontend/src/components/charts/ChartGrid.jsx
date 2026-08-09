import { AnomalyVolumeChart } from "./AnomalyVolumeChart";
import { ReportsOverTimeChart } from "./ReportsOverTimeChart";
import { SeverityChart } from "./SeverityChart";
import { TopAttackTypesChart } from "./TopAttackTypesChart";

/**
 * The four dashboard charts, in one default-exported module.
 *
 * This exists to be `React.lazy`-ed. Recharts is ~400 kB of the bundle and
 * /dashboard is the landing route, so importing it eagerly puts the whole
 * charting library in front of the first paint. Behind a lazy boundary it
 * downloads in parallel with the aggregate requests it is waiting on anyway,
 * and the rest of the app — every route that draws no charts — never pays for
 * it at all.
 *
 * Nothing else in the app may import `recharts` directly, or the chunk merges
 * back into the entry bundle and this stops working.
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
