import createClient from "openapi-fetch";

import type { components, paths } from "./schema";

/**
 * Snapshot builds are a read-only static copy of the demo investigations: every API response
 * was saved as a file under /snapshot, so the console needs no server (see scripts/snapshot.py).
 */
export const SNAPSHOT = process.env.NEXT_PUBLIC_SNAPSHOT === "1";
const BASE_PATH = process.env.NEXT_PUBLIC_BASE_PATH ?? "";

/** Base URL of the ORIGIN API, baked in at build time. */
export const API_URL = SNAPSHOT
  ? `${BASE_PATH}/snapshot`
  : (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000");

/** In a snapshot, a GET of /x/y is served by the file /snapshot/x/y.json; nothing else is. */
export function snapshotFetch(request: Request): Promise<Response> {
  if (request.method !== "GET") {
    return Promise.resolve(
      new Response(JSON.stringify({ detail: "This is a read-only snapshot of the demo. Run ORIGIN locally to trace images." }), {
        status: 405,
        headers: { "content-type": "application/json" },
      }),
    );
  }
  const url = new URL(request.url);
  return globalThis.fetch(`${url.pathname.replace(/\/$/, "")}.json`, { signal: request.signal });
}

/** Typed client generated from the API's OpenAPI schema (`make client`). */
export const api = createClient<paths>({
  baseUrl: API_URL,
  // Resolve fetch per request rather than capturing it at import time.
  fetch: (request) => (SNAPSHOT ? snapshotFetch(request) : globalThis.fetch(request)),
});

export type Readyz = components["schemas"]["Readyz"];
export type DependencyCheck = components["schemas"]["DependencyCheck"];
export type RunOut = components["schemas"]["RunOut"];
export type CaseOut = components["schemas"]["CaseOut"];
export type AssetOut = components["schemas"]["AssetOut"];
export type CredentialsOut = components["schemas"]["CredentialsOut"];
export type MetadataOut = components["schemas"]["MetadataOut"];
export type RunSightingsOut = components["schemas"]["RunSightingsOut"];
export type SightingOut = components["schemas"]["SightingOut"];
export type RunAnalysisOut = components["schemas"]["RunAnalysisOut"];
export type ClaimOut = components["schemas"]["ClaimOut"];
export type NarrativeOut = components["schemas"]["NarrativeOut"];
export type EvidencePack = components["schemas"]["EvidencePack"];
