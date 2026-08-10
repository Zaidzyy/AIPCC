import { API_BASE_URL } from "@/lib/apiClient";
import { getToken } from "@/lib/token";

/**
 * Reading the report-generation event stream.
 *
 * `fetch` + a `ReadableStream`, not `EventSource`. `EventSource` cannot set an
 * `Authorization` header and its only workaround is a token in the query
 * string — which this app refuses on principle, and which would be worse than
 * a principle here because the backend writes an access-log line for every
 * request. The extra thirty lines below are what keeps the JWT out of the URL,
 * the log and the browser history.
 *
 * This is the one place in the app that does not go through the axios client:
 * axios buffers the whole body before resolving, which is exactly the
 * behaviour a stream exists to avoid.
 */

const DECODER = new TextDecoder();

/** Parse one SSE frame. Returns null for comments and keep-alives. */
function parseFrame(block) {
  let name = null;
  const data = [];
  for (const line of block.split("\n")) {
    if (line.startsWith("event:")) name = line.slice(6).trim();
    else if (line.startsWith("data:")) data.push(line.slice(5).trim());
    // Anything else — a `: heartbeat` comment, a `retry:` field — is ignored,
    // which is what the SSE spec requires of an unknown field.
  }
  if (!name || data.length === 0) return null;
  try {
    return { event: name, data: JSON.parse(data.join("\n")) };
  } catch {
    // A frame we cannot read must not kill the stream: the sections that
    // already landed are still good, and the terminal frame may still arrive.
    return null;
  }
}

export async function streamGeneration(
  { documentId, reportName, classification },
  { onEvent, signal } = {},
) {
  const response = await fetch(`${API_BASE_URL}/generate_report/stream`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "text/event-stream",
      ...(getToken() ? { Authorization: `Bearer ${getToken()}` } : {}),
    },
    body: JSON.stringify({
      document_id: documentId,
      report_name: reportName,
      classification,
    }),
    signal,
  });

  if (!response.ok) {
    // The refusals happen before the body starts, so they are ordinary JSON.
    let detail = `Generation could not be started (${response.status}).`;
    try {
      const body = await response.json();
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      /* A non-JSON error body is still a failure; the status carries it. */
    }
    const error = new Error(detail);
    error.status = response.status;
    throw error;
  }

  const reader = response.body.getReader();
  let buffer = "";

  // Frames are separated by a blank line and can be split across chunks, so
  // the tail of the buffer is kept until its terminator arrives. Reading
  // chunk-by-chunk and hoping each one holds a whole frame works on localhost
  // and stops working behind anything that repackages the bytes.
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += DECODER.decode(value, { stream: true });

    let split;
    while ((split = buffer.indexOf("\n\n")) !== -1) {
      const frame = parseFrame(buffer.slice(0, split));
      buffer = buffer.slice(split + 2);
      if (frame) onEvent?.(frame);
    }
  }
}
