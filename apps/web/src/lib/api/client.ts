import createClient from "openapi-fetch";

import type { components, paths } from "./schema";

/** Base URL of the ORIGIN API, baked in at build time. */
export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

/** Typed client generated from the API's OpenAPI schema (`make client`). */
export const api = createClient<paths>({
  baseUrl: API_URL,
  // Resolve fetch per request rather than capturing it at import time.
  fetch: (request) => globalThis.fetch(request),
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
