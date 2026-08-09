import { cn } from "@/lib/utils";

export function Skeleton({ className, ...props }) {
  return (
    <div
      className={cn("animate-shimmer rounded-sm bg-raised", className)}
      {...props}
    />
  );
}

/** Placeholder rows shaped like the table they stand in for. */
export function SkeletonRows({ rows = 5, columns = 4 }) {
  return (
    <div className="divide-y divide-line/70">
      {Array.from({ length: rows }, (_, row) => (
        <div key={row} className="flex items-center gap-4 px-4 py-3.5">
          {Array.from({ length: columns }, (_, column) => (
            <Skeleton
              key={column}
              className="h-3.5"
              style={{ width: column === 0 ? "28%" : `${18 - column * 2}%` }}
            />
          ))}
        </div>
      ))}
    </div>
  );
}
