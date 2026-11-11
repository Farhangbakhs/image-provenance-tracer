import type { SightingOut } from "./api/client";
import { SIGNAL_LABEL } from "./copy";
import { formatUtc } from "./time";

/**
 * Plain-language definitions for every term the console uses. Shown on hover or focus of a
 * <Term>, and in full in the "How to read this" guide.
 */
export const GLOSSARY = {
  sighting:
    "A place where ORIGIN found this picture and proved it is the same image, by fetching it and comparing it pixel by pixel. A search hit that has not been checked is only a candidate.",
  candidate:
    "A hit from a search engine. ORIGIN fetches every candidate itself; only those that match become sightings.",
  exact: "Byte-for-byte the same file as the one you uploaded.",
  near_duplicate:
    "The same picture, perhaps resized or recompressed. Its perceptual hash is within a few bits of yours.",
  derivative:
    "An edited copy: cropped, mirrored or with text added. Confirmed by matching features in the picture, not just by similarity.",
  variant:
    "A group of copies that look the same (same crop, same overlay). Arrows between variants show which edit came from which.",
  narrative:
    "A story told about the picture: what it shows, where and when. The first story found is the root; a contradicting story opens a branch.",
  divergence: "The earliest sighting where a branch's story appears: the point where the story changed.",
  earliest:
    "The earliest copy among the sightings ORIGIN found. Not the origin: earlier copies may exist in places search engines do not index.",
  interval:
    "When a copy was first online, given as a range: no earlier than the first date, and proven to exist by the second.",
  confidence:
    "How strong the dating evidence is. High: a platform's own timestamp or a signed credential. Medium: an archive capture or a page's stated date. Low: weak hints only.",
  reliability:
    "Admiralty grade for the source (A to F). A is completely reliable; F means its reliability cannot be judged, the default until an analyst grades the source.",
  credibility:
    "Admiralty grade for this sighting (1 to 6). 1 is confirmed by independent evidence; 6 cannot be judged.",
  forward:
    "A Telegram post that says it was forwarded from another public post. Recorded by Telegram itself, so it is a real link, not an inference.",
  platform: "The time the platform itself shows for the post. The strongest dating evidence.",
} as const;

export type GlossaryKey = keyof typeof GLOSSARY;

export const MATCH_LABEL: Record<string, string> = {
  exact: "identical file",
  near_duplicate: "same picture",
  derivative: "edited copy",
};

const EDIT_WORD: Record<string, string> = {
  crop: "cropped",
  mirror: "mirrored",
  resize: "resized",
  overlay: "text or graphics added",
  recompress: "recompressed",
};

function edits(sighting: SightingOut): string[] {
  const list = (sighting.transform as { edits?: unknown } | null)?.edits;
  return Array.isArray(list) ? list.filter((e): e is string => typeof e === "string") : [];
}

/** "Same picture, resized." / "Edited copy: cropped, text added." */
export function explainMatch(sighting: SightingOut): string {
  const words = edits(sighting).map((e) => EDIT_WORD[e] ?? e);
  if (sighting.match_class === "exact") return "Identical file to yours.";
  if (sighting.match_class === "near_duplicate")
    return words.length ? `Same picture, ${words.join(", ")}.` : "Same picture, possibly resized or recompressed.";
  return words.length ? `Edited copy: ${words.join(", ")}.` : "Edited copy of your picture.";
}

/** What dated this copy, in words: "Online by 18 Jul 2014 (archive capture of the page)." */
export function explainDate(sighting: SightingOut): string {
  const deciding = sighting.deciding;
  const lower = sighting.date_lower ? formatUtc(sighting.date_lower, "day") : null;
  const upper = sighting.date_upper ? formatUtc(sighting.date_upper, "day") : null;
  const why = deciding ? SIGNAL_LABEL[deciding.kind] ?? deciding.kind : null;
  if (deciding?.bound === "exact" && lower) return `Posted ${lower}${why ? ` (${why})` : ""}.`;
  if (lower && upper && lower !== upper)
    return `First online between ${lower} and ${upper}${why ? `, dated by the ${why}` : ""}.`;
  if (upper) return `Online by ${upper}${why ? ` (${why})` : ""}.`;
  return "No dating evidence was found.";
}

/** "Source not yet graded (F); sighting credibility 4 of 6." */
export function explainGrade(sighting: SightingOut): string | null {
  if (!sighting.reliability && !sighting.credibility) return null;
  const source =
    sighting.reliability === "F" || !sighting.reliability
      ? "source not yet graded (F)"
      : `source reliability ${sighting.reliability}`;
  const cred = sighting.credibility ? `credibility ${sighting.credibility} of 6` : "credibility not judged";
  return `${source[0].toUpperCase()}${source.slice(1)}; ${cred}.`;
}
