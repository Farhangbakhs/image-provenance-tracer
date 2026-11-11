import type { NarrativeOut, RunAnalysisOut, RunSightingsOut, SightingOut } from "./api/client";

/** Lane for sightings whose page made no claim about the picture (or was not read). */
export const NO_CLAIM_LANE = "no-claim";

export interface Lane {
  id: string;
  label: string;
  /** The root narrative is the story told by the earliest-dated claim. */
  root: boolean;
  narrative?: NarrativeOut;
}

export interface WorkspaceModel {
  sightings: SightingOut[];
  earliestId: string | null;
  lanes: Lane[];
  laneOf: Record<string, string>;
  /** Narrative id -> the sighting where it first appears (its divergence point). */
  divergenceOf: Record<string, string>;
  variantLabel: Record<string, string>;
}

/** Combine the sightings list and the branching analysis into what the three views share. */
export function buildWorkspace(sightings: RunSightingsOut, analysis: RunAnalysisOut | undefined): WorkspaceModel {
  const narratives = analysis?.narratives ?? [];
  const claims = analysis?.claims ?? [];
  const narrativeOfClaim: Record<string, string> = {};
  for (const n of narratives) for (const c of n.claim_ids) narrativeOfClaim[c] = n.id;

  const laneOf: Record<string, string> = {};
  for (const s of sightings.sightings) laneOf[s.id] = NO_CLAIM_LANE;
  for (const c of claims) {
    const narrative = narrativeOfClaim[c.id];
    if (narrative) laneOf[c.sighting_id] = narrative;
  }

  const ordered = [...narratives].sort((a, b) => Number(a.parent_narrative_id !== null) - Number(b.parent_narrative_id !== null));
  const lanes: Lane[] = ordered.map((n) => ({
    id: n.id,
    label: n.label,
    root: n.parent_narrative_id === null,
    narrative: n,
  }));
  if (Object.values(laneOf).includes(NO_CLAIM_LANE) || lanes.length === 0) {
    lanes.push({ id: NO_CLAIM_LANE, label: lanes.length ? "No claim read" : "Sightings", root: false });
  }

  const variantLabel: Record<string, string> = {};
  for (const v of analysis?.variants ?? []) for (const id of v.sighting_ids) variantLabel[id] = v.label;

  return {
    sightings: sightings.sightings,
    earliestId: sightings.earliest_sighting_id ?? null,
    lanes,
    laneOf,
    divergenceOf: Object.fromEntries(narratives.map((n) => [n.id, n.divergence_sighting_id])),
    variantLabel,
  };
}

/** The next sighting for j/k navigation, wrapping at the ends. */
export function step(ids: string[], current: string | null, delta: 1 | -1): string | null {
  if (ids.length === 0) return null;
  const index = current ? ids.indexOf(current) : -1;
  if (index === -1) return delta === 1 ? ids[0] : ids[ids.length - 1];
  return ids[(index + delta + ids.length) % ids.length];
}

export const CONFIDENCE_COLOUR: Record<string, string> = {
  high: "var(--conf-high)",
  medium: "var(--conf-medium)",
  low: "var(--conf-low)",
  unknown: "var(--muted)",
};
