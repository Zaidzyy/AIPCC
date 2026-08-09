import * as SwitchPrimitive from "@radix-ui/react-switch";

import { cn } from "@/lib/utils";

export function Switch({ className, ...props }) {
  return (
    <SwitchPrimitive.Root
      className={cn(
        "peer inline-flex h-5 w-9 shrink-0 cursor-pointer items-center rounded-full",
        "border border-line-strong transition-colors",
        "data-[state=unchecked]:bg-raised data-[state=checked]:border-ink data-[state=checked]:bg-ink",
        "disabled:cursor-not-allowed disabled:opacity-50",
        className,
      )}
      {...props}
    >
      <SwitchPrimitive.Thumb
        className={cn(
          "pointer-events-none block size-3.5 rounded-full transition-transform",
          "data-[state=unchecked]:translate-x-0.5 data-[state=unchecked]:bg-ink-faint",
          "data-[state=checked]:translate-x-4.5 data-[state=checked]:bg-void",
        )}
      />
    </SwitchPrimitive.Root>
  );
}
