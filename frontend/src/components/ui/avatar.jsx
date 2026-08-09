import { cn } from "@/lib/utils";

/**
 * Initials only. There is no avatar upload in the API, so a component that
 * renders an image slot would be advertising a feature that does not exist.
 */
export function Avatar({ initials, className, size = "md" }) {
  return (
    <span
      className={cn(
        "inline-flex shrink-0 select-none items-center justify-center rounded-md",
        "border border-line-strong bg-raised font-mono font-medium text-ink-dim",
        size === "sm" && "size-7 text-[0.6875rem]",
        size === "md" && "size-8 text-xs",
        size === "lg" && "size-12 text-sm",
        className,
      )}
      aria-hidden="true"
    >
      {initials}
    </span>
  );
}
