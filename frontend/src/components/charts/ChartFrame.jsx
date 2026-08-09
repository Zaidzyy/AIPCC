import { ResponsiveContainer } from "recharts";

import { Card, CardBody, CardHeader, CardTitle, EmptyState, ErrorState, Skeleton } from "@/components/ui";

/**
 * The four states every chart on this page has to be able to be in.
 *
 * "Empty" is not "failed" and neither is "loading" — a fresh install has no
 * reports and its dashboard has to look deliberate rather than broken. Every
 * chart routes through here so none of them can forget one of the four.
 */
export function ChartFrame({
  title,
  description,
  query,
  isEmpty,
  emptyTitle = "No data yet",
  emptyDescription,
  emptyIcon,
  height = 220,
  actions,
  children,
}) {
  const empty = query.data !== undefined && isEmpty(query.data);

  return (
    <Card className="flex flex-col">
      <CardHeader>
        <div className="min-w-0">
          <CardTitle>{title}</CardTitle>
          {description && (
            <p className="mt-1 text-[0.8125rem] leading-snug text-ink-faint">{description}</p>
          )}
        </div>
        {actions}
      </CardHeader>

      {query.isError ? (
        <ErrorState error={query.error} title={`Could not load ${title.toLowerCase()}`} onRetry={query.refetch} />
      ) : query.isPending ? (
        <CardBody>
          <Skeleton style={{ height }} className="w-full" />
        </CardBody>
      ) : empty ? (
        <EmptyState icon={emptyIcon} title={emptyTitle} description={emptyDescription} />
      ) : (
        <CardBody className="pt-1">
          {/* Recharts measures its parent, so the height lives on the wrapper
              and the container is told to fill it. */}
          <div style={{ height }} className="w-full">
            <ResponsiveContainer width="100%" height="100%">
              {children(query.data)}
            </ResponsiveContainer>
          </div>
        </CardBody>
      )}
    </Card>
  );
}

/**
 * Tooltip in the app's own chrome. Recharts' default is a white card, which is
 * the one surface in this UI that would read as a rendering fault.
 */
export function ChartTooltip({ active, payload, label, labelFormatter, valueFormatter }) {
  if (!active || !payload?.length) return null;

  return (
    <div className="rounded-md border border-line-strong bg-overlay px-3 py-2 shadow-pop">
      {label !== undefined && (
        // The formatter receives the payload too, so a chart whose axis label
        // had to be truncated to fit can show the whole thing here.
        <p className="eyebrow mb-1.5">
          {labelFormatter ? labelFormatter(label, payload) : label}
        </p>
      )}
      <ul className="space-y-1">
        {payload.map((entry) => (
          <li key={entry.dataKey ?? entry.name} className="flex items-center gap-2 text-xs">
            <span
              className="size-2 shrink-0 rounded-[2px]"
              style={{ background: entry.color ?? entry.fill }}
              aria-hidden="true"
            />
            <span className="text-ink-dim">{entry.name}</span>
            <span className="ml-auto pl-3 font-mono tabular-nums text-ink">
              {valueFormatter ? valueFormatter(entry.value) : entry.value}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
