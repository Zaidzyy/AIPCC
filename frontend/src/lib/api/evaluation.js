import { apiClient } from "@/lib/apiClient";

/**
 * The last committed evaluation run.
 *
 * Read-only: the harness is a command (`python -m app.eval.run`), not an
 * endpoint. A live evaluation costs money and takes half a minute, so an API
 * that triggered one would be a bill with a refresh button.
 */
export async function latest() {
  const { data } = await apiClient.get("/eval/latest");
  return data;
}
