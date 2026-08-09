import { useQuery } from "@tanstack/react-query";
import { ChevronDown, LogOut, Menu, Settings, UserRound } from "lucide-react";
import { Link, useNavigate } from "react-router-dom";

import {
  Avatar,
  Button,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
  Tooltip,
} from "@/components/ui";
import { useAuth } from "@/context/AuthContext";
import { apiClient } from "@/lib/apiClient";
import { fullName, initials } from "@/lib/format";
import { cn } from "@/lib/utils";

export function Topbar({ onOpenNav }) {
  const { user } = useAuth();

  return (
    <header className="sticky top-0 z-30 flex h-14 items-center justify-between gap-4 border-b border-line bg-void/85 px-4 backdrop-blur-md lg:px-8">
      <Button
        variant="ghost"
        size="icon-sm"
        className="lg:hidden"
        onClick={onOpenNav}
        aria-label="Open navigation"
      >
        <Menu />
      </Button>

      <div className="flex-1" />

      <div className="flex items-center gap-3">
        <DatabaseStatus />
        <span className="h-5 w-px bg-line" aria-hidden="true" />
        <UserMenu user={user} />
      </div>
    </header>
  );
}

/**
 * A live readiness signal rather than a decorative badge — it polls the real
 * `/health/db` probe. In a console whose whole job is telling you when
 * something is wrong, a fake status light would be the worst kind of chrome.
 */
function DatabaseStatus() {
  const { data, isError, isPending } = useQuery({
    queryKey: ["health", "db"],
    queryFn: async () => (await apiClient.get("/health/db")).data,
    refetchInterval: 60_000,
    retry: false,
  });

  const state = isPending ? "checking" : isError ? "down" : "up";
  const copy = {
    checking: { label: "Checking", dot: "bg-info", tip: "Checking the API" },
    up: { label: "Online", dot: "bg-ok", tip: `Database ${data?.database ?? "reachable"}` },
    down: { label: "Offline", dot: "bg-critical", tip: "The API is not reachable" },
  }[state];

  return (
    <Tooltip content={copy.tip}>
      <span className="hidden items-center gap-2 sm:inline-flex">
        <span
          className={cn(
            "size-1.5 rounded-full",
            copy.dot,
            state === "up" && "animate-pulse-dot",
          )}
          aria-hidden="true"
        />
        <span className="eyebrow">{copy.label}</span>
      </span>
    </Tooltip>
  );
}

function UserMenu({ user }) {
  const { logout } = useAuth();
  const navigate = useNavigate();

  if (!user) return null;

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          className="flex items-center gap-2 rounded-md py-1 pl-1 pr-1.5 transition-colors hover:bg-raised"
        >
          <Avatar initials={initials(user)} size="sm" />
          <span className="hidden text-sm text-ink-dim sm:inline">{fullName(user)}</span>
          <ChevronDown className="size-3.5 text-ink-faint" aria-hidden="true" />
        </button>
      </DropdownMenuTrigger>

      <DropdownMenuContent align="end" className="min-w-56">
        <DropdownMenuLabel>{user.email}</DropdownMenuLabel>
        <DropdownMenuItem asChild>
          <Link to="/profile">
            <UserRound />
            Profile
          </Link>
        </DropdownMenuItem>
        <DropdownMenuItem asChild>
          <Link to="/settings">
            <Settings />
            Settings
          </Link>
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem
          destructive
          onSelect={() => {
            logout();
            navigate("/login", { replace: true });
          }}
        >
          <LogOut />
          Sign out
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
