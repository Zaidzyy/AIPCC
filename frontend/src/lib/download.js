/**
 * Saving a generated file the browser handed us as a blob.
 *
 * The export endpoints require an `Authorization` header, so they cannot be a
 * plain `<a href>` — the browser would fetch them unauthenticated and get a
 * 401. The file comes back through the same axios client as everything else
 * and is handed to the user from memory here.
 */

/** The server's filename, from `Content-Disposition`. */
export function filenameFromResponse(response, fallback) {
  const disposition = response?.headers?.["content-disposition"] ?? "";
  const match = /filename="?([^";]+)"?/i.exec(disposition);
  return match?.[1] ?? fallback;
}

export function saveBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  // Revoked on the next task, not synchronously: Safari and Firefox cancel a
  // download whose object URL is released in the same tick as the click.
  setTimeout(() => URL.revokeObjectURL(url), 0);
}
