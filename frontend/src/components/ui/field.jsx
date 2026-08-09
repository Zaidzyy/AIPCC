import * as LabelPrimitive from "@radix-ui/react-label";
import { useId } from "react";

import { cn } from "@/lib/utils";

export function Label({ className, ...props }) {
  return (
    <LabelPrimitive.Root
      className={cn("eyebrow block text-ink-dim", className)}
      {...props}
    />
  );
}

const controlStyles =
  "w-full rounded-md border border-line-strong bg-void px-3 text-sm text-ink " +
  "placeholder:text-ink-faint transition-colors " +
  "hover:border-ink-faint focus:border-ink focus:outline-none " +
  "disabled:opacity-50 disabled:cursor-not-allowed " +
  "aria-[invalid=true]:border-critical/60";

export function Input({ className, ...props }) {
  return <input className={cn(controlStyles, "h-9.5", className)} {...props} />;
}

export function Textarea({ className, ...props }) {
  return (
    <textarea
      className={cn(controlStyles, "min-h-24 resize-y py-2 leading-relaxed", className)}
      {...props}
    />
  );
}

/**
 * Label + control + message, wired together.
 *
 * The message slot is the same element whether it holds a hint or an error, so
 * a field cannot show both at once and the layout does not shift when one
 * replaces the other.
 */
export function Field({ label, hint, error, required, children, className }) {
  const id = useId();
  const messageId = `${id}-message`;
  const message = error || hint;

  return (
    <div className={cn("space-y-1.5", className)}>
      {label && (
        <Label htmlFor={id}>
          {label}
          {required && <span className="ml-1 text-critical">*</span>}
        </Label>
      )}
      {children({
        id,
        "aria-invalid": error ? true : undefined,
        "aria-describedby": message ? messageId : undefined,
      })}
      {message && (
        <p
          id={messageId}
          className={cn("text-[0.8125rem]", error ? "text-critical" : "text-ink-faint")}
        >
          {message}
        </p>
      )}
    </div>
  );
}
