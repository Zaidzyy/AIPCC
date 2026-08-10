import { afterEach, describe, expect, it, vi } from "vitest";

import { streamGeneration } from "./stream";

/**
 * The SSE reader, tested on the thing that breaks in production and not in
 * development: frame boundaries.
 *
 * On localhost every write arrives as its own chunk and a naive parser that
 * assumes "one chunk is one frame" passes every manual test. Put a proxy in
 * front of it and the bytes get repackaged — two frames in one chunk, one
 * frame split across two — and the stream silently loses events.
 */
const encoder = new TextEncoder();

function respondWith(chunks, { ok = true, status = 200, json = null } = {}) {
  const queue = chunks.map((chunk) => encoder.encode(chunk));
  vi.stubGlobal("fetch", async () => ({
    ok,
    status,
    json: async () => json,
    body: {
      getReader: () => ({
        read: async () =>
          queue.length ? { value: queue.shift(), done: false } : { done: true },
      }),
    },
  }));
}

async function collect(chunks) {
  respondWith(chunks);
  const seen = [];
  await streamGeneration(
    { documentId: "d", reportName: "r", classification: "Internal" },
    { onEvent: (frame) => seen.push(frame) },
  );
  return seen;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("streamGeneration", () => {
  it("reads two frames delivered in one chunk", async () => {
    const seen = await collect([
      'event: started\ndata: {"report_id":"abc","sections":["timeline"]}\n\n' +
        'event: section\ndata: {"section":"timeline","state":"started"}\n\n',
    ]);

    expect(seen.map((f) => f.event)).toEqual(["started", "section"]);
    expect(seen[0].data.report_id).toBe("abc");
  });

  it("reads one frame split across chunks", async () => {
    const seen = await collect([
      'event: sec',
      'tion\ndata: {"section":"anomalies",',
      '"state":"completed","items":3}\n',
      "\n",
    ]);

    expect(seen).toHaveLength(1);
    expect(seen[0].data).toMatchObject({ section: "anomalies", items: 3 });
  });

  it("ignores heartbeat comments", async () => {
    const seen = await collect([
      ": heartbeat\n\n",
      'event: stored\ndata: {"report_id":"abc","status":"complete"}\n\n',
    ]);

    expect(seen.map((f) => f.event)).toEqual(["stored"]);
  });

  it("skips a malformed frame instead of killing the stream", async () => {
    const seen = await collect([
      "event: section\ndata: {not json\n\n",
      'event: stored\ndata: {"status":"complete"}\n\n',
    ]);

    // The sections that already landed are still good and the terminal frame
    // may still arrive — throwing here would lose both.
    expect(seen.map((f) => f.event)).toEqual(["stored"]);
  });

  it("throws with the server's detail when the stream is refused", async () => {
    respondWith([], { ok: false, status: 404, json: { detail: "document not found" } });

    await expect(
      streamGeneration({ documentId: "d", reportName: "r", classification: "Internal" }),
    ).rejects.toThrow("document not found");
  });
});
