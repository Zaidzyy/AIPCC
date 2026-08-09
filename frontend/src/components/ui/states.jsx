import { AlertTriangle, RotateCw } from "lucide-react";

import { Button } from "@/components/ui/button";
import { errorMessage } from "@/lib/apiClient";
import { cn } from "@/lib/utils";

/**
 * The three states every data view needs.
 *
 * They live together because they are the same layout at three different
 * temperatures, and keeping them in one file makes it obvious when a page has
 * wired up only one of them.
 */

export function EmptyState({ icon: Icon, title, description, action, className }) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center px-6 py-16 text-center",
        className,
      )}
    >
      {Icon && (
        <div className="mb-4 rounded-lg border border-line bg-raised p-3">
          <Icon className="size-5 text-ink-faint" aria-hidden="true" />
        </div>
      )}
      <p className="font-mono text-sm font-medium text-ink">{title}</p>
      {description && (
        <p className="mt-1.5 max-w-sm text-sm text-ink-dim">{description}</p>
      )}
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}

/**
 * An error is a warning, so it is allowed colour. It always names what failed
 * and offers the next action — never a bare "Something went wrong".
 */
export function ErrorState({ error, title = "Could not load this", onRetry, className }) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center px-6 py-16 text-center",
        className,
      )}
    >
      <div className="mb-4 rounded-lg border border-critical/30 bg-critical/10 p-3">
        <AlertTriangle className="size-5 text-critical" aria-hidden="true" />
      </div>
      <p className="font-mono text-sm font-medium text-ink">{title}</p>
      <p className="mt-1.5 max-w-md text-sm text-ink-dim">{errorMessage(error)}</p>
      {onRetry && (
        <Button size="sm" className="mt-5" onClick={onRetry}>
          <RotateCw />
          Try again
        </Button>
      )}
    </div>
  );
}

/** A quiet inline spinner for regions that are already framed. */
export function LoadingState({ label = "Loading", className }) {
  return (
    <div
      className={cn("flex items-center justify-center gap-2.5 px-6 py-16", className)}
      role="status"
    >
      <span className="size-1.5 animate-pulse-dot rounded-full bg-ink-faint" />
      <span className="eyebrow">{label}</span>
    </div>
  );
}
