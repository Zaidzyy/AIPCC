import { useCallback, useEffect, useRef, useState } from "react";

import { reportsApi } from "@/lib/api";
import { streamGeneration } from "@/lib/api/stream";

/**
 * One report generation, watched.
 *
 * Three failure cases were designed for rather than discovered, because all
 * three are ordinary during a run that takes a minute:
 *
 * 1. **A section fails permanently.** Its row goes red and carries the typed
 *    `SectionError`; the other four keep going and the report is still stored.
 * 2. **The connection drops mid-generation.** The report row already exists —
 *    its id arrived in the opening event — and the work is not driven by the
 *    stream, so the generation is still running on the server. The hook falls
 *    back to polling `GET /reports/{id}/status`, which is what that endpoint
 *    was for. It never restarts generation: that would pay for the same report
 *    twice and store it twice.
 * 3. **The user navigates away and comes back.** The in-flight id is written to
 *    `sessionStorage`, so remounting resumes case 2 rather than losing the run.
 *    Session-scoped, not local: a report in flight is not interesting in
 *    another tab a week later.
 */

const RESUME_KEY = "aipcc.generation";
const POLL_MS = 2500;
const TERMINAL = new Set(["complete", "partial", "failed"]);

function readResume() {
  try {
    const raw = sessionStorage.getItem(RESUME_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

function writeResume(value) {
  try {
    if (value) sessionStorage.setItem(RESUME_KEY, JSON.stringify(value));
    else sessionStorage.removeItem(RESUME_KEY);
  } catch {
    /* Storage unavailable — reconnect after a remount simply will not work. */
  }
}

const initial = {
  // idle | streaming | reconnecting | done | error
  phase: "idle",
  reportId: null,
  reportName: "",
  sections: [],
  result: null,
  error: null,
};

export function useGenerationStream() {
  const [state, setState] = useState(initial);
  const abortRef = useRef(null);
  const pollRef = useRef(null);

  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  /** Fall back to the status endpoint. Never restarts generation. */
  const reconnect = useCallback(
    (reportId, reportName) => {
      setState((prev) => ({
        ...prev,
        phase: "reconnecting",
        reportId,
        reportName: prev.reportName || reportName || "",
      }));
      stopPolling();
      pollRef.current = setInterval(async () => {
        try {
          const status = await reportsApi.status(reportId);
          if (!TERMINAL.has(status.status)) return;
          stopPolling();
          writeResume(null);
          setState((prev) => ({
            ...prev,
            phase: "done",
            result: { report_id: reportId, status: status.status, errors: [] },
          }));
        } catch (error) {
          // A 404 means the report is gone; anything else is transient and
          // the next tick will try again.
          if (error?.response?.status === 404) {
            stopPolling();
            writeResume(null);
            setState((prev) => ({ ...prev, phase: "error", error }));
          }
        }
      }, POLL_MS);
    },
    [stopPolling],
  );

  // Resume an in-flight generation on mount. Runs once; a run started by this
  // component writes the same key and would otherwise resume itself.
  useEffect(() => {
    const pending = readResume();
    if (pending?.reportId) reconnect(pending.reportId, pending.reportName);
    return () => {
      stopPolling();
      abortRef.current?.abort();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const start = useCallback(
    async ({ documentId, reportName, classification }) => {
      const controller = new AbortController();
      abortRef.current = controller;
      setState({ ...initial, phase: "streaming", reportName });

      let reportId = null;
      let terminal = false;
      try {
        await streamGeneration(
          { documentId, reportName, classification },
          {
            signal: controller.signal,
            onEvent: ({ event, data }) => {
              if (event === "started") {
                reportId = data.report_id;
                writeResume({ reportId, reportName });
                setState((prev) => ({
                  ...prev,
                  reportId,
                  // Every section is listed as pending up front, so the list
                  // never reflows and the outstanding work is visible from the
                  // first frame.
                  sections: data.sections.map((name) => ({
                    name,
                    state: "pending",
                    attempt: 1,
                  })),
                }));
              } else if (event === "section") {
                setState((prev) => ({
                  ...prev,
                  sections: prev.sections.map((section) =>
                    section.name === data.section
                      ? {
                          ...section,
                          ...data,
                          name: section.name,
                          // A client-side stamp, only for the live counter on
                          // a section still running. The server's elapsed_ms
                          // is authoritative once a section settles, but on
                          // `started` it is always ~0 — a number frozen at
                          // 0.0s beside a spinner reads as broken.
                          startedAt:
                            data.state === "started" ? Date.now() : section.startedAt,
                        }
                      : section,
                  ),
                }));
              } else if (event === "stored") {
                terminal = true;
                writeResume(null);
                setState((prev) => ({ ...prev, phase: "done", result: data }));
              }
            },
          },
        );
        if (!terminal && reportId) {
          // The body ended without the terminal frame — a proxy timeout, or a
          // dropped connection that looked like a clean close. The generation
          // is unaffected; watch it through the status endpoint.
          reconnect(reportId, reportName);
        }
      } catch (error) {
        if (controller.signal.aborted) return;
        if (reportId) {
          // The generation is still running server-side; only the stream
          // broke. Watch it through the status endpoint instead.
          reconnect(reportId, reportName);
          return;
        }
        writeResume(null);
        setState((prev) => ({ ...prev, phase: "error", error }));
      }
    },
    [reconnect],
  );

  const reset = useCallback(() => {
    stopPolling();
    abortRef.current?.abort();
    writeResume(null);
    setState(initial);
  }, [stopPolling]);

  return { ...state, start, reset };
}
