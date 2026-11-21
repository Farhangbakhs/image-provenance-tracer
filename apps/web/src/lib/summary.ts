import type { RunAnalysisOut, RunSightingsOut, SightingOut } from "./api/client";
import { bareDomain } from "./domain";
import { buildStories } from "./stories";
import { formatDay } from "./time";
import { NO_CLAIM_LANE, type WorkspaceModel } from "./workspace";

/** One piece of the sentence: plain text, or a domain that selects its copy when clicked. */
export type SummaryPart = { text: string } | { domain: string; sightingId: string };

export interface RunSummary {
  parts: SummaryPart[];
  /** The numbers under the sentence, from the stored candidate counts. */
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

/** A story's name exactly as stored, in quotes. */
const story = (label: string) => `“${label}”`;

/**
 * The counts under the answer, every one a stored candidate count. "Not matched" is what ORIGIN
 * opened and could not turn into a copy; "blocked" is Google's own redirect page; "not checked"
 * is what ranked below the checking limit. Blocked is always shown, even at zero.
 */
export function buildFacts(counts: Counts): string[] {
  return [
    `${counts.verified} verified`,
    `${counts.unrelated + counts.fetch_failed} not matched`,
    `${counts.blocked} blocked`,
    `${counts.pending} not checked`,
  ];
}

/**
 * The answer in two or three short sentences, built only from stored fields (no model call).
 * Where the evidence is thin the sentence says so instead of reaching for a story.
 */
export function buildSummary(
  model: WorkspaceModel,
  analysis: RunAnalysisOut | undefined,
  counts: Counts,
): RunSummary {
  const facts = buildFacts(counts);
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
  const lane = model.laneOf[earliest.id];
  const own = narratives.find((n) => n.id === lane) ?? null;
  const inRoot = root !== null && own?.id === root.id;

  const parts: SummaryPart[] = [
    { text: `First found ${when(earliest)} on ` },
    { domain: bareDomain(earliest.domain), sightingId: earliest.id },
  ];

  if (inRoot) {
    parts.push({ text: `, telling ${story(root.label)}.` });
  } else if (own) {
    parts.push({ text: `, telling ${story(own.label)}.` });
  } else {
    // A copy with no story of its own, while other copies do tell one: its caption was not readable.
    parts.push({ text: narratives.length > 0 && (lane === undefined || lane === NO_CLAIM_LANE) ? " (caption unreadable)." : "." });
  }

  // When the earliest copy does not tell the original story, say where that story first appears.
  if (root && !inRoot) {
    const origin = buildStories(model, analysis, true).rows.find((r) => r.root)?.first ?? null;
    if (origin) {
      parts.push(
        { text: ` Earliest readable story: ${story(root.label)} on ` },
        { domain: bareDomain(origin.domain), sightingId: origin.id },
        { text: `, ${when(origin)}.` },
      );
    } else {
      parts.push({ text: ` Earliest readable story: ${story(root.label)}.` });
    }
  }

  let tail: string;
  if (model.sightings.length === 1) {
    tail = " It is the only verified copy.";
  } else if (narratives.length === 0) {
    tail = " No captions could be read from the copies checked.";
  } else if (retold === 0) {
    tail = " No retellings found among the copies checked.";
  } else if (retold === 1) {
    tail = " Since reused in 1 other story, contradicting it.";
  } else {
    tail = ` Since reused in ${retold} other stories, all contradicting it.`;
  }
  parts.push({ text: tail });
  return { parts, facts };
}
