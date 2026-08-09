import { Link } from "react-router-dom";

import { Button } from "@/components/ui";

export function NotFound() {
  return (
    <div className="flex min-h-[60vh] flex-col items-center justify-center text-center">
      <p className="eyebrow">404</p>
      <h1 className="mt-3 font-mono text-2xl font-semibold tracking-[-0.03em] text-ink">
        No such page
      </h1>
      <p className="mt-2 max-w-sm text-sm text-ink-dim">
        The address you followed does not match a route in this application.
      </p>
      <Button variant="primary" className="mt-6" asChild>
        <Link to="/dashboard">Back to the dashboard</Link>
      </Button>
    </div>
  );
}
