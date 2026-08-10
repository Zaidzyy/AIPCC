import { apiClient } from "@/lib/apiClient";
import { filenameFromResponse } from "@/lib/download";

/**
 * The ATT&CK matrix.
 *
 * Two reads with very different lifetimes, which is why they are two calls
 * rather than one: the grid is MITRE's published data and never changes
 * between deploys, while the detections change every time a report is
 * generated. Fetching them together would put an 89 KB catalogue behind every
 * refresh of a number that moves.
 */

export async function matrix() {
  const { data } = await apiClient.get("/attack/matrix");
  return data;
}

export async function detections(reportId) {
  const { data } = await apiClient.get(
    reportId ? `/attack/detections/${reportId}` : "/attack/detections",
  );
  return data;
}

export async function navigatorLayer(reportId) {
  const response = await apiClient.get(
    reportId ? `/attack/navigator-layer/${reportId}` : "/attack/navigator-layer",
    { responseType: "blob" },
  );
  return {
    blob: response.data,
    filename: filenameFromResponse(response, "aipcc-navigator.json"),
  };
}
