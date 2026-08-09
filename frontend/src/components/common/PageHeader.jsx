import { cn } from "@/lib/utils";

/**
 * Every page opens the same way: an eyebrow naming the section, a mono title,
 * and optional actions on the right. The eyebrow is not decoration — it is the
 * same label used in the sidebar, so a page always says where you are.
 */
export function PageHeader({ eyebrow, title, description, actions, children, className }) {
  return (
    <header className={cn("mb-7", className)}>
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          {eyebrow && <p className="eyebrow mb-2">{eyebrow}</p>}
          <h1 className="font-mono text-2xl font-semibold tracking-[-0.03em] text-ink">
            {title}
          </h1>
          {description && (
            <p className="mt-2 max-w-2xl text-sm leading-relaxed text-ink-dim">
              {description}
            </p>
          )}
        </div>
        {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
      </div>
      {children}
    </header>
  );
}
