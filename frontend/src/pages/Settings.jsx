import { useQuery } from "@tanstack/react-query";
import { LogOut, RotateCw } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { PageHeader } from "@/components/common/PageHeader";
import {
  Badge,
  Button,
  Card,
  CardBody,
  CardHeader,
  CardTitle,
  Switch,
  useToast,
} from "@/components/ui";
import { useAuth } from "@/context/AuthContext";
import { API_BASE_URL, apiClient } from "@/lib/apiClient";
import { fullName } from "@/lib/format";
import { cn } from "@/lib/utils";

const INTRO_KEY = "aipcc.intro-played";

export function Settings() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  return (
    <>
      <PageHeader
        eyebrow="Account"
        title="Settings"
        description="How this browser is talking to the AIPCC backend."
      />

      <div className="grid gap-6 lg:grid-cols-2">
        <Connection />

        <Card className="self-start">
          <CardHeader>
            <CardTitle>Session</CardTitle>
          </CardHeader>
          <CardBody className="space-y-4">
            <Row label="Signed in as" value={fullName(user)} />
            <Row label="Role" value={<Badge>{user?.role}</Badge>} />
            <Row
              label="Token"
              value={
                <span className="text-ink-dim">
                  Held in this browser only, sent as a bearer header on every request.
                </span>
              }
            />
            <Button
              variant="danger"
              className="w-full"
              onClick={() => {
                logout();
                navigate("/login", { replace: true });
              }}
            >
              <LogOut />
              Sign out
            </Button>
          </CardBody>
        </Card>

        <Interface />
        <About />
      </div>
    </>
  );
}

function Connection() {
  const health = useQuery({
    queryKey: ["health", "db"],
    queryFn: async () => (await apiClient.get("/health/db")).data,
    retry: false,
  });

  const state = health.isPending ? "checking" : health.isError ? "down" : "up";
  const dot = { checking: "bg-info", up: "bg-ok", down: "bg-critical" }[state];
  const copy = {
    checking: "Checking…",
    up: "The API is reachable and Postgres is responding.",
    down: "The API did not answer. Start the backend, then check again.",
  }[state];

  return (
    <Card className="self-start">
      <CardHeader>
        <CardTitle>Connection</CardTitle>
        <Button
          variant="ghost"
          size="icon-sm"
          onClick={() => health.refetch()}
          aria-label="Check again"
        >
          <RotateCw className={cn(health.isFetching && "animate-spin")} />
        </Button>
      </CardHeader>
      <CardBody className="space-y-4">
        <Row
          label="API base URL"
          value={<span className="ident break-all">{API_BASE_URL}</span>}
        />
        <Row
          label="Status"
          value={
            <span className="flex items-center gap-2">
              <span className={cn("size-1.5 rounded-full", dot)} aria-hidden="true" />
              <span className="text-ink-dim">{copy}</span>
            </span>
          }
        />
        <p className="border-t border-line pt-3 text-xs text-ink-faint">
          Set <span className="ident">VITE_API_BASE_URL</span> to point this build at a different
          backend.
        </p>
      </CardBody>
    </Card>
  );
}

/**
 * The intro replay is a real preference backed by real storage, not a toggle
 * that looks like a setting and does nothing.
 */
function Interface() {
  const { toast } = useToast();
  const [replay, setReplay] = useState(() => {
    try {
      return sessionStorage.getItem(INTRO_KEY) !== "1";
    } catch {
      return false;
    }
  });

  function handleChange(value) {
    setReplay(value);
    try {
      if (value) sessionStorage.removeItem(INTRO_KEY);
      else sessionStorage.setItem(INTRO_KEY, "1");
    } catch {
      /* Storage unavailable — nothing to persist. */
    }
    toast({
      title: value ? "Intro will play" : "Intro is off",
      description: value ? "It runs once the next time you sign in." : "It stays skipped for this session.",
    });
  }

  return (
    <Card className="self-start">
      <CardHeader>
        <CardTitle>Interface</CardTitle>
      </CardHeader>
      <CardBody>
        <label className="flex items-start justify-between gap-6">
          <span>
            <span className="block text-sm text-ink">Play the intro sequence</span>
            <span className="mt-1 block text-[0.8125rem] text-ink-dim">
              A five-second title card on entry. It is skipped automatically if your system
              requests reduced motion — the clip ends in a full-screen flash.
            </span>
          </span>
          <Switch checked={replay} onCheckedChange={handleChange} aria-label="Play the intro sequence" />
        </label>
      </CardBody>
    </Card>
  );
}

function About() {
  return (
    <Card className="self-start">
      <CardHeader>
        <CardTitle>About</CardTitle>
      </CardHeader>
      <CardBody className="space-y-4">
        <Row label="Application" value="AIPCC — AI-Powered Cybersecurity Co-Pilot" />
        <Row
          label="Pipeline"
          value="Logs are chunked, embedded with all-MiniLM-L6-v2 and stored in Chroma. Reports are five LLM sections, each validated against the report schema before it reaches the database."
        />
        <Row
          label="Report sections"
          value="Attack types · Risk assessment · Vulnerabilities · Anomalies · Timeline"
        />
      </CardBody>
    </Card>
  );
}

function Row({ label, value }) {
  return (
    <div>
      <p className="eyebrow">{label}</p>
      <div className="mt-1 text-sm text-ink-dim">{value}</div>
    </div>
  );
}
