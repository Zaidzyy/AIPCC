import {
  FileText,
  LayoutDashboard,
  MessageSquare,
  Settings,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
  UserRound,
  Users,
} from "lucide-react";
import { NavLink } from "react-router-dom";

import { useAuth } from "@/context/AuthContext";
import { cn } from "@/lib/utils";

/**
 * Nav groups double as the page eyebrows — "ANALYSIS" here is the same word
 * that appears above the title on /reports. Structure encodes where you are.
 */
const GROUPS = [
  {
    label: "Analysis",
    items: [
      { to: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
      { to: "/generate", label: "Generate", icon: Sparkles },
      { to: "/reports", label: "Reports", icon: FileText },
      { to: "/alerts", label: "Alerts", icon: ShieldAlert },
      { to: "/chat", label: "Chat", icon: MessageSquare },
    ],
  },
  {
    label: "Administration",
    adminOnly: true,
    items: [{ to: "/users", label: "Users", icon: Users }],
  },
  {
    label: "Account",
    items: [
      { to: "/profile", label: "Profile", icon: UserRound },
      { to: "/settings", label: "Settings", icon: Settings },
    ],
  },
];

export function Sidebar({ onNavigate }) {
  const { isAdmin } = useAuth();

  return (
    <nav className="flex h-full flex-col gap-7 overflow-y-auto px-3 py-5">
      <Brand />

      {GROUPS.filter((group) => !group.adminOnly || isAdmin).map((group) => (
        <div key={group.label} className="space-y-1">
          <p className="eyebrow px-2.5 pb-1.5">{group.label}</p>
          {group.items.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              onClick={onNavigate}
              className={({ isActive }) =>
                cn(
                  "group relative flex items-center gap-2.5 rounded-md px-2.5 py-1.5 text-sm transition-colors",
                  isActive
                    ? "bg-raised font-medium text-ink"
                    : "text-ink-dim hover:bg-raised/60 hover:text-ink",
                )
              }
            >
              {({ isActive }) => (
                <>
                  {/* The active marker is a white rule, not a coloured pill. */}
                  <span
                    className={cn(
                      "absolute left-0 h-4 w-0.5 rounded-r-full bg-ink transition-opacity",
                      isActive ? "opacity-100" : "opacity-0",
                    )}
                    aria-hidden="true"
                  />
                  <Icon className="size-4 shrink-0" aria-hidden="true" />
                  {label}
                </>
              )}
            </NavLink>
          ))}
        </div>
      ))}
    </nav>
  );
}

function Brand() {
  return (
    <div className="flex items-center gap-2.5 px-2.5">
      <ShieldCheck className="size-5 text-ink" aria-hidden="true" />
      <div className="leading-none">
        <p className="font-mono text-sm font-bold tracking-[-0.02em] text-ink">AIPCC</p>
        <p className="eyebrow mt-1 text-[0.625rem]">Security Co-Pilot</p>
      </div>
    </div>
  );
}
