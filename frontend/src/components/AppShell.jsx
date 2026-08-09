import { Outlet } from 'react-router-dom'

/**
 * Minimal layout shell. Phase 3 replaces this with the real sidebar + topbar
 * against the design system.
 */
export default function AppShell() {
  return (
    <div className="min-h-screen bg-console-bg text-console-text">
      <header className="border-b border-console-border px-6 py-4">
        <span className="font-semibold tracking-wide">AIPCC</span>
        <span className="ml-2 text-sm text-console-muted">
          AI-Powered Cybersecurity Co-Pilot
        </span>
      </header>
      <main className="p-6">
        <Outlet />
      </main>
    </div>
  )
}
