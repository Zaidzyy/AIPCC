import { AlertTriangle, Check, Circle, Loader2, RotateCcw, WifiOff } from "lucide-react";
import { useEffect, useState } from "react";

import { AmbientVideo } from "@/components/common/AmbientVideo";
import { Card, CardBody } from "@/components/ui";
import { cn } from "@/lib/utils";

/**
 * Five sections, filling in live.
 *
 * The `retrying` row is the reason this screen exists. A section that fails
 * validation and recovers on the repair prompt is the system demonstrating the
 * robustness this project claims — behind a spinner it is invisible, and a
 * reviewer has no way to know it happened at all. So it gets a row of its own
 * colour, and the reason the first attempt was rejected is shown verbatim.
 *
 * Colour follows the app's rule: amber is a warning (a retry), red is a
 * failure, and the rest of the screen stays graphite. Progress is not a
 * severity and gets no hue.
 */

const LABELS = {
  attack_types: "Attack types",
  general_risk_assessment: "Risk assessment",
  vulnerabilities: "Vulnerabilities",
  anomalies: "Anomalies",
  timeline: "Timeline",
};

const STATES = {
  pending: {
    icon: Circle,
    tone: "text-ink-faint",
    label: "Queued",
  },
  started: {
    icon: Loader2,
    tone: "text-ink",
    label: "Analysing",
    spin: true,
  },
  retrying: {
    icon: RotateCcw,
    tone: "text-medium",
    label: "Retrying — repair prompt",
  },
  completed: {
    icon: Check,
    tone: "text-ok",
    label: "Complete",
  },
  failed: {
    icon: AlertTriangle,
    tone: "text-critical",
    label: "Failed",
  },
};

const RUNNING = new Set(["started", "retrying"]);

export function GenerationProgress({ name, sections, reconnecting = false }) {
  const settled = sections.filter((s) => s.state === "completed" || s.state === "failed");
  const running = sections.some((s) => RUNNING.has(s.state));

  // One timer for the whole list rather than one per row, and only while
  // something is actually running — a section that has settled has a fixed
  // number and does not need re-rendering once a second forever. The clock is
  // held in state rather than read during render, because a render that calls
  // `Date.now()` is not a pure function of its props.
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!running) return undefined;
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [running]);

  return (
    <div className="mx-auto max-w-2xl">
      <div className="mb-7 flex flex-col items-center text-center">
        <div className="relative mb-5 size-24 overflow-hidden rounded-full">
          <AmbientVideo clip="loading-ring" opacity="opacity-90" scrim="bg-transparent" />
        </div>
        <p className="font-mono text-base font-medium text-ink">
          Generating {name || "report"}
        </p>
        <p className="mt-2 max-w-md text-sm text-ink-dim">
          {reconnecting ? (
            <>
              The event stream dropped, but generation is still running on the server.
              Watching its status instead — nothing has been restarted.
            </>
          ) : (
            <>
              Five sections are being written concurrently and validated against the report
              schema. {settled.length} of {sections.length || 5} settled.
            </>
          )}
        </p>
      </div>

      {reconnecting ? (
        <Card>
          <CardBody className="flex items-center gap-3">
            <WifiOff className="size-4 shrink-0 text-medium" aria-hidden="true" />
            <p className="text-sm text-ink-dim">
              Reconnected to the report&rsquo;s status. This page will open it as soon as it
              finishes.
            </p>
          </CardBody>
        </Card>
      ) : (
        <ul className="space-y-2">
          {sections.map((section) => (
            <SectionRow key={section.name} section={section} now={now} />
          ))}
        </ul>
      )}
    </div>
  );
}

/**
 * A live count while the section runs; the server's own measurement once it
 * settles. Two sources on purpose: only the server knows how long the work
 * took, and only the client can tick while it is still taking it.
 */
function Elapsed({ section, now }) {
  if (section.state === "pending") return null;

  const seconds = RUNNING.has(section.state)
    ? section.startedAt
      ? Math.max(0, now - section.startedAt) / 1000
      : null
    : section.elapsed_ms != null
      ? section.elapsed_ms / 1000
      : null;

  if (seconds == null) return null;
  return (
    <span className="font-mono text-xs text-ink-faint tabular-nums">
      {seconds.toFixed(1)}s
    </span>
  );
}

function SectionRow({ section, now }) {
  const state = STATES[section.state] ?? STATES.pending;
  const Icon = state.icon;

  return (
    <li
      className={cn(
        "rounded-md border bg-surface px-4 py-3 transition-colors",
        section.state === "failed" && "border-critical/35",
        section.state === "retrying" && "border-medium/45",
        section.state !== "failed" && section.state !== "retrying" && "border-line",
      )}
    >
      <div className="flex items-center gap-3">
        <Icon
          className={cn("size-4 shrink-0", state.tone, state.spin && "animate-spin")}
          aria-hidden="true"
        />
        <span className="ident min-w-0 flex-1 truncate text-ink">
          {LABELS[section.name] ?? section.name}
        </span>
        <span className={cn("text-xs", state.tone)}>{state.label}</span>
        <Elapsed section={section} now={now} />
      </div>

      {section.state === "completed" && (
        <p className="mt-1.5 pl-7 text-xs text-ink-faint">
          {section.items} finding{section.items === 1 ? "" : "s"}
          {section.ungrounded > 0 && (
            // Surfaced here as well as on the report: a finding with no valid
            // citation is the number this project refuses to hide.
            <span className="text-medium"> · {section.ungrounded} ungrounded</span>
          )}
        </p>
      )}

      {section.state === "retrying" && section.reason && (
        <p className="mt-1.5 pl-7 text-xs text-medium">
          First attempt rejected — {section.reason}
        </p>
      )}

      {section.state === "failed" && section.error && (
        <p className="mt-1.5 pl-7 text-xs text-critical">
          <span className="text-ink-faint">({section.error.stage})</span>{" "}
          {section.error.detail}
        </p>
      )}
    </li>
  );
}
