import { cn } from "@/lib/utils";

/**
 * Tables scroll inside their own container so a wide findings table never
 * makes the page body scroll horizontally.
 */
export function Table({ className, ...props }) {
  return (
    <div className="w-full overflow-x-auto">
      <table
        className={cn("w-full border-collapse text-sm", className)}
        {...props}
      />
    </div>
  );
}

export function THead({ className, ...props }) {
  return <thead className={cn("border-b border-line", className)} {...props} />;
}

export function TBody({ className, ...props }) {
  return (
    <tbody className={cn("divide-y divide-line/70", className)} {...props} />
  );
}

export function TR({ className, ...props }) {
  return (
    <tr className={cn("transition-colors hover:bg-raised/60", className)} {...props} />
  );
}

export function TH({ className, ...props }) {
  return (
    <th
      scope="col"
      className={cn("eyebrow px-4 py-2.5 text-left font-medium", className)}
      {...props}
    />
  );
}

export function TD({ className, ...props }) {
  return (
    <td className={cn("px-4 py-3 align-top text-ink-dim", className)} {...props} />
  );
}
