import * as DialogPrimitive from "@radix-ui/react-dialog";
import { X } from "lucide-react";
import { useState } from "react";
import { Outlet } from "react-router-dom";

import { Sidebar } from "@/components/layout/Sidebar";
import { Topbar } from "@/components/layout/Topbar";

/**
 * The one shell every authenticated page renders inside: persistent sidebar on
 * large screens, a drawer below that, and a sticky topbar.
 *
 * The prototype had no shell and no router — every page was stacked into
 * App.jsx at once. See CLAUDE.md > Hard rules.
 */
export function AppShell() {
  const [navOpen, setNavOpen] = useState(false);

  return (
    <div className="min-h-dvh lg:grid lg:grid-cols-[15rem_1fr]">
      <aside className="sticky top-0 hidden h-dvh border-r border-line bg-surface lg:block">
        <Sidebar />
      </aside>

      <MobileNav open={navOpen} onOpenChange={setNavOpen} />

      <div className="flex min-w-0 flex-col">
        <Topbar onOpenNav={() => setNavOpen(true)} />
        <main className="flex-1 px-4 py-7 lg:px-8 lg:py-9">
          <div className="mx-auto w-full max-w-6xl">
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  );
}

function MobileNav({ open, onOpenChange }) {
  return (
    <DialogPrimitive.Root open={open} onOpenChange={onOpenChange}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className="fixed inset-0 z-50 bg-void/80 backdrop-blur-sm data-[state=open]:animate-fade lg:hidden" />
        <DialogPrimitive.Content className="fixed inset-y-0 left-0 z-50 w-64 border-r border-line bg-surface shadow-pop data-[state=open]:animate-fade lg:hidden">
          <DialogPrimitive.Title className="sr-only">Navigation</DialogPrimitive.Title>
          <DialogPrimitive.Close
            className="absolute right-3 top-4 rounded-sm p-1 text-ink-faint transition-colors hover:bg-raised hover:text-ink"
            aria-label="Close navigation"
          >
            <X className="size-4" />
          </DialogPrimitive.Close>
          <Sidebar onNavigate={() => onOpenChange(false)} />
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}
