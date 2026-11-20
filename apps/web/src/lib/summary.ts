import type { RunAnalysisOut, RunSightingsOut, SightingOut } from "./api/client";
import { formatDay } from "./time";
import type { WorkspaceModel } from "./workspace";

/** One piece of the sentence: plain text, or a domain that selects its copy when clicked. */
export type SummaryPart = { text: string } | { domain: string; sightingId: string };

export interface RunSummary {
  parts: SummaryPart[];
  /** The numbers under the sentence; zero counts are left out. */
  facts: string[];
}

type Counts = RunSightingsOut["candidates"];

const YEAR_MS = 365 * 86_400_000;

/** A date range wider than a year says little about when the copy appeared. */
export function isUncertain(s: SightingOut): boolean {
  if (!s.date_lower || !s.date_upper) return true;
  return new Date(s.date_upper).getTime() - new Date(s.date_lower).getTime() > YEAR_MS;
}

function when(s: SightingOut): string {
  const day = s.date_upper ?? s.date_lower;
  if (!day) return "an unknown date";
  // A proven upper bound over a wide range is "by", not "on": the copy was online by then.
  return isUncertain(s) ? `by ${formatDay(day)}` : formatDay(day);
}

const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;

/**
 * The answer in one sentence, built only from stored fields (no model call). Where the evidence
 * is thin the sentence says so instead of reaching for a story.
 */
export function buildSummary(
  model: WorkspaceModel,
  analysis: RunAnalysisOut | undefined,
  counts: Counts,
): RunSummary {
  const facts = [
    `${counts.verified} verified`,
    ...(counts.blocked ? [`${counts.blocked} blocked`] : []),
    ...(counts.pending ? [`${counts.pending} not checked`] : []),
  ];
  const earliest = model.sightings.find((s) => s.id === model.earliestId) ?? null;

  if (!earliest) {
    const text =
      counts.verified === 0 && counts.blocked > 0
        ? `No copy could be checked: Google's redirect pages blocked ${plural(counts.blocked, "result", "results")}. ` +
          "Trace again in a few minutes; the search is reused, so it costs nothing."
        : "No verified copy of this picture was found.";
    return { parts: [{ text }], facts };
  }

  const narratives = analysis?.narratives ?? [];
  const root = narratives.find((n) => n.parent_narrative_id === null) ?? null;
  const retold = narratives.filter((n) => n.parent_narrative_id !== null).length;
  const inRoot = root !== null && model.laneOf[earliest.id] === root.id;

  const parts: SummaryPart[] = [
    { text: `First found ${when(earliest)} on ` },
    { domain: earliest.domain, sightingId: earliest.id },
  ];
  let tail = inRoot ? ` as ${root.label}.` : ".";
  if (!inRoot && root) tail = `, whose caption could not be read. The original story is ${root.label}.`;

  if (model.sightings.length === 1) {
    tail += " It is the only verified copy.";
  } else if (narratives.length === 0) {
    tail += " No captions could be read from the copies checked.";
  } else if (retold === 0) {
    tail += " No retellings found among the copies checked.";
  } else if (retold === 1) {
    tail += " Since reused in 1 other story, which contradicts it.";
  } else {
    tail += ` Since reused in ${retold} other stories, all ${retold} of which contradict it.`;
  }
  parts.push({ text: tail });
  return { parts, facts };
}
