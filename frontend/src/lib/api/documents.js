import { apiClient } from "@/lib/apiClient";

export async function list() {
  const { data } = await apiClient.get("/documents");
  return data;
}

export async function get(documentId) {
  const { data } = await apiClient.get(`/documents/${documentId}`);
  return data;
}

/**
 * Upload and ingest a log file.
 *
 * Ingestion is synchronous on the backend — embedding runs before the response
 * — so `onProgress` reports the upload only. The wait afterwards is the
 * vector store, and the UI says so rather than leaving a stalled bar at 100%.
 */
export async function upload(file, onProgress) {
  const body = new FormData();
  body.append("file", file);

  const { data } = await apiClient.post("/upload_file", body, {
    onUploadProgress: (event) => {
      if (!onProgress || !event.total) return;
      onProgress(Math.round((event.loaded / event.total) * 100));
    },
  });
  return data;
}
