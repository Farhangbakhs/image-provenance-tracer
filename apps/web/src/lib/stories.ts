import type { RunAnalysisOut, SightingOut } from "./api/client";
import { NO_CLAIM_LANE, type WorkspaceModel } from "./workspace";

/** Only these two exist in the data: the first story, and a story that contradicts it. */
export type StoryStatus = "Original story" | "Contradicts original";

export interface StoryRow {
  id: string;
  label: string;
  status: StoryStatus;
  root: boolean;
  /** Oldest first, by the earliest date the evidence proves. */
  copies: SightingOut[];
  first: SightingOut | null;
  summary: string | null;
  /** Why the model judged this story to contradict the original. */
  reason: string | null;
}

export interface StoryModel {
  /** Every story: the original first, then by the date of each one's first copy. */
  rows: StoryRow[];
  /** The rows on show: the first {@link MAX_ROWS}, or all when asked. */
  shown: StoryRow[];
  hidden: number;
  /** Copies whose page made no claim, or whose text could not be read. */
  uncaptioned: SightingOut[];
}

export const MAX_ROWS = 6;

/** The date a copy is proven online by (its upper bound), else its lower bound; unknown last. */
export function provenAt(s: SightingOut | null | undefined): number {
  const v = s?.date_upper ?? s?.date_lower;
  return v ? new Date(v).getTime() : Number.POSITIVE_INFINITY;
}

export function byProvenDate(a: SightingOut, b: SightingOut): number {
  return provenAt(a) - provenAt(b);
}

/** One row per story, in the order a reader should take them, and the copies with no caption. */
export function buildStories(model: WorkspaceModel, analysis: RunAnalysisOut | undefined, showAll = false): StoryModel {
  const narratives = analysis?.narratives ?? [];
  const rows: StoryRow[] = narratives.map((n) => {
    const copies = model.sightings.filter((s) => model.laneOf[s.id] === n.id).sort(byProvenDate);
    const root = n.parent_narrative_id === null;
    return {
      id: n.id,
      label: n.label,
      status: root ? "Original story" : "Contradicts original",
      root,
      copies,
      first: copies[0] ?? null,
      summary: n.summary ?? null,
      reason: n.divergence_reason ?? null,
    };
  });
  rows.sort((a, b) => Number(b.root) - Number(a.root) || provenAt(a.first) - provenAt(b.first));
  const shown = showAll ? rows : rows.slice(0, MAX_ROWS);
  return {
    rows,
    shown,
    hidden: rows.length - shown.length,
    uncaptioned: model.sightings.filter((s) => model.laneOf[s.id] === NO_CLAIM_LANE).sort(byProvenDate),
  };
}

/** "3 copies", "1 copy". */
export function copyCount(n: number): string {
  return `${n} cop${n === 1 ? "y" : "ies"}`;
}
