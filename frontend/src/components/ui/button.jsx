import { Slot } from "@radix-ui/react-slot";
import { cva } from "class-variance-authority";
import { Loader2 } from "lucide-react";

import { cn } from "@/lib/utils";

/**
 * The primary action is white on graphite, not a coloured accent — colour in
 * this UI means severity (see index.css). The one exception is `danger`:
 * a destructive action *is* a warning, so it is allowed the critical hue.
 */
const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 rounded-md font-medium whitespace-nowrap " +
    "transition-colors duration-150 select-none " +
    "disabled:pointer-events-none disabled:opacity-40 " +
    "[&_svg]:shrink-0 [&_svg]:size-4",
  {
    variants: {
      variant: {
        primary: "bg-ink text-void hover:bg-white active:bg-ink/90",
        secondary:
          "bg-raised text-ink border border-line-strong hover:bg-overlay hover:border-ink-faint",
        ghost: "text-ink-dim hover:bg-raised hover:text-ink",
        danger:
          "bg-critical/10 text-critical border border-critical/30 hover:bg-critical/20 hover:border-critical/50",
        link: "text-ink underline underline-offset-4 decoration-line-strong hover:decoration-ink",
      },
      size: {
        sm: "h-8 px-3 text-[0.8125rem]",
        md: "h-9.5 px-4 text-sm",
        lg: "h-11 px-6 text-[0.9375rem]",
        icon: "size-9 p-0",
        "icon-sm": "size-8 p-0",
      },
    },
    defaultVariants: { variant: "secondary", size: "md" },
  },
);

export function Button({
  className,
  variant,
  size,
  asChild = false,
  loading = false,
  disabled,
  children,
  ...props
}) {
  const Component = asChild ? Slot : "button";
  return (
    <Component
      className={cn(buttonVariants({ variant, size }), className)}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      {...props}
    >
      {loading ? (
        <>
          <Loader2 className="animate-spin" aria-hidden="true" />
          {children}
        </>
      ) : (
        children
      )}
    </Component>
  );
}

export { buttonVariants };
