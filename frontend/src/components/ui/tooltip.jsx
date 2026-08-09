import * as TooltipPrimitive from "@radix-ui/react-tooltip";

import { cn } from "@/lib/utils";

export const TooltipProvider = TooltipPrimitive.Provider;

/** Trigger + content in one component; the bare Radix parts are rarely needed. */
export function Tooltip({ content, children, side = "top", delayDuration = 300 }) {
  if (!content) return children;

  return (
    <TooltipPrimitive.Root delayDuration={delayDuration}>
      <TooltipPrimitive.Trigger asChild>{children}</TooltipPrimitive.Trigger>
      <TooltipPrimitive.Portal>
        <TooltipPrimitive.Content
          side={side}
          sideOffset={6}
          className={cn(
            "z-50 max-w-72 rounded-md border border-line-strong bg-overlay",
            "px-2.5 py-1.5 text-[0.8125rem] text-ink shadow-pop",
            "data-[state=delayed-open]:animate-fade",
          )}
        >
          {content}
        </TooltipPrimitive.Content>
      </TooltipPrimitive.Portal>
    </TooltipPrimitive.Root>
  );
}
