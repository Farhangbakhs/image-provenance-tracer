import { api, type Readyz } from "./api/client";

export type ReadinessView =
  | { kind: "ready"; body: Readyz }
  | { kind: "degraded"; body: Readyz }
  | { kind: "unreachable"; message: string };

/**
 * The API answers /readyz with 200 when every dependency is up and 503 with the same body
 * when one is down; a network failure means the API itself is unreachable.
 */
export async function fetchReadiness(signal?: AbortSignal): Promise<ReadinessView> {
  try {
    const { data, error, response } = await api.GET("/readyz", { signal });
    if (data) return { kind: "ready", body: data };
    if (response.status === 503 && error) return { kind: "degraded", body: error };
    return { kind: "unreachable", message: `API answered HTTP ${response.status}` };
  } catch (err) {
    if (signal?.aborted) throw err;
    return { kind: "unreachable", message: err instanceof Error ? err.message : String(err) };
  }
}

export const DEPENDENCY_LABELS: Record<string, string> = {
  database: "Database",
  redis: "Job queue",
  storage: "Object storage",
};
