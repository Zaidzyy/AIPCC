import * as ToastPrimitive from "@radix-ui/react-toast";
import { AlertTriangle, Check, Info, X } from "lucide-react";
import { createContext, useCallback, useContext, useMemo, useState } from "react";

import { cn } from "@/lib/utils";

const ToastContext = createContext(null);

const VARIANTS = {
  success: { icon: Check, className: "text-ok" },
  error: { icon: AlertTriangle, className: "text-critical" },
  info: { icon: Info, className: "text-ink-dim" },
};

let nextId = 0;

export function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([]);

  const dismiss = useCallback((id) => {
    setToasts((current) => current.filter((item) => item.id !== id));
  }, []);

  const toast = useCallback(({ title, description, variant = "info" }) => {
    const id = ++nextId;
    setToasts((current) => [...current, { id, title, description, variant }]);
    return id;
  }, []);

  const value = useMemo(() => ({ toast, dismiss }), [toast, dismiss]);

  return (
    <ToastContext.Provider value={value}>
      <ToastPrimitive.Provider swipeDirection="right" duration={5000}>
        {children}
        {toasts.map(({ id, title, description, variant }) => {
          const { icon: Icon, className } = VARIANTS[variant] ?? VARIANTS.info;
          return (
            <ToastPrimitive.Root
              key={id}
              onOpenChange={(open) => !open && dismiss(id)}
              className={cn(
                "flex items-start gap-3 rounded-md border border-line-strong bg-overlay",
                "p-3.5 pr-10 shadow-pop data-[state=open]:animate-rise",
                "data-[swipe=end]:translate-x-[var(--radix-toast-swipe-end-x)]",
              )}
            >
              <Icon className={cn("mt-0.5 size-4 shrink-0", className)} aria-hidden="true" />
              <div className="min-w-0 flex-1">
                <ToastPrimitive.Title className="font-mono text-[0.8125rem] font-medium text-ink">
                  {title}
                </ToastPrimitive.Title>
                {description && (
                  <ToastPrimitive.Description className="mt-0.5 text-[0.8125rem] leading-snug text-ink-dim">
                    {description}
                  </ToastPrimitive.Description>
                )}
              </div>
              <ToastPrimitive.Close
                className="absolute right-2.5 top-2.5 rounded-sm p-1 text-ink-faint transition-colors hover:bg-raised hover:text-ink"
                aria-label="Dismiss"
              >
                <X className="size-3.5" />
              </ToastPrimitive.Close>
            </ToastPrimitive.Root>
          );
        })}
        <ToastPrimitive.Viewport className="fixed bottom-0 right-0 z-[100] flex w-96 max-w-[calc(100vw-2rem)] flex-col gap-2 p-4 outline-none" />
      </ToastPrimitive.Provider>
    </ToastContext.Provider>
  );
}

export function useToast() {
  const context = useContext(ToastContext);
  if (!context) throw new Error("useToast must be used inside <ToastProvider>");
  return context;
}
