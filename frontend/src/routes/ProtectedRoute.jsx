import { Navigate, Outlet, useLocation } from "react-router-dom";

import { useAuth } from "@/context/AuthContext";

/**
 * Gate for every authenticated route.
 *
 * While a stored token is still being exchanged for a user we render a quiet
 * placeholder rather than redirecting — bouncing to /login on every refresh
 * and back again is the classic version of this bug.
 */
export function ProtectedRoute() {
  const { isAuthenticated, isResolving } = useAuth();
  const location = useLocation();

  if (isResolving) return <SessionSplash />;

  if (!isAuthenticated) {
    // Remember where they were headed so login can return them to it.
    return <Navigate to="/login" replace state={{ from: location }} />;
  }

  return <Outlet />;
}

/** Admin-only routes. Analysts are sent to the dashboard, not to /login. */
export function AdminRoute() {
  const { isAdmin, isResolving } = useAuth();

  if (isResolving) return <SessionSplash />;
  if (!isAdmin) return <Navigate to="/dashboard" replace />;

  return <Outlet />;
}

function SessionSplash() {
  return (
    <div className="flex min-h-dvh items-center justify-center" role="status">
      <div className="flex items-center gap-2.5">
        <span className="size-1.5 animate-pulse-dot rounded-full bg-ink-faint" />
        <span className="eyebrow">Restoring session</span>
      </div>
    </div>
  );
}
