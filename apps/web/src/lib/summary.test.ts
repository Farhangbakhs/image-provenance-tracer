import { describe, expect, it } from "vitest";

import type { NarrativeOut, RunAnalysisOut, SightingOut } from "./api/client";
import { buildSummary, isUncertain, type RunSummary } from "./summary";
import type { WorkspaceModel } from "./workspace";

const counts = { pending: 0, verified: 3, unrelated: 0, fetch_failed: 0, blocked: 0 };

function sighting(id: string, domain: string, lower: string | null, upper: string | null): SightingOut {
  return { id, domain, date_lower: lower, date_upper: upper } as unknown as SightingOut;
}

function model(
  sightings: SightingOut[],
  laneOf: Record<string, string> = {},
  earliestId: string | null = sightings[0]?.id ?? null,
): WorkspaceModel {
  return { sightings, earliestId, lanes: [], laneOf, divergenceOf: {}, variantLabel: {} };
}

const narrative = (id: string, label: string, parent: string | null): NarrativeOut =>
  ({ id, label, parent_narrative_id: parent, claim_ids: [], divergence_sighting_id: "s1" }) as unknown as NarrativeOut;

const analysis = (narratives: NarrativeOut[]) => ({ narratives }) as unknown as RunAnalysisOut;

const text = (s: RunSummary) => s.parts.map((p) => ("text" in p ? p.text : p.domain)).join("");

const first = sighting("s1", "valencia-news.example", "2024-10-30T07:40:00Z", "2024-10-30T08:15:00Z");
const second = sighting("s2", "iberia.example", "2024-11-04T10:00:00Z", "2024-11-05T12:00:00Z");
const third = sighting("s3", "viral.example", "2024-11-11T18:00:00Z", "2024-11-12T09:00:00Z");

describe("buildSummary", () => {
  it("names the first copy, its story, and how many stories contradict it", () => {
    const m = model([first, second, third], { s1: "root", s2: "root", s3: "b1" });
    const s = buildSummary(
      m,
      analysis([narrative("root", "Floods in Valencia", null), narrative("b1", "Hurricane Milton", "root")]),
      counts,
    );
    expect(text(s)).toBe(
      "First found 30 Oct 2024 on valencia-news.example as Floods in Valencia. Since reused in 1 other story, which contradicts it.",
    );
    expect(s.facts).toEqual(["3 verified"]);
  });

  it("says all of several retellings contradict it", () => {
    const m = model([first, second, third], { s1: "root" });
    const s = buildSummary(
      m,
      analysis([narrative("root", "Original", null), narrative("b1", "A", "root"), narrative("b2", "B", "root")]),
      counts,
    );
    expect(text(s)).toContain("Since reused in 2 other stories, all 2 of which contradict it.");
  });

  it("makes the domain a link to its copy", () => {
    const s = buildSummary(model([first]), undefined, counts);
    expect(s.parts[1]).toEqual({ domain: "valencia-news.example", sightingId: "s1" });
  });

  it("with no narratives says no captions could be read", () => {
    const s = buildSummary(model([first, second]), analysis([]), counts);
    expect(text(s)).toBe("First found 30 Oct 2024 on valencia-news.example. No captions could be read from the copies checked.");
  });

  it("with one narrative says no retellings were found", () => {
    const m = model([first, second], { s1: "root" });
    const s = buildSummary(m, analysis([narrative("root", "Floods in Valencia", null)]), counts);
    expect(text(s)).toBe(
      "First found 30 Oct 2024 on valencia-news.example as Floods in Valencia. No retellings found among the copies checked.",
    );
  });

  it("with a single sighting says it is the only copy", () => {
    const s = buildSummary(model([first]), analysis([]), { ...counts, verified: 1 });
    expect(text(s)).toBe("First found 30 Oct 2024 on valencia-news.example. It is the only verified copy.");
  });

  it("does not claim a story for a first copy whose caption could not be read", () => {
    const m = model([first, second], { s2: "root" });
    const s = buildSummary(m, analysis([narrative("root", "Floods", null)]), counts);
    expect(text(s)).toContain("whose caption could not be read. The original story is Floods.");
  });

  it("says by, not on, when the date range is wide", () => {
    const wide = sighting("w", "slow.example", "2014-01-01T00:00:00Z", "2026-11-20T00:00:00Z");
    expect(isUncertain(wide)).toBe(true);
    expect(text(buildSummary(model([wide]), undefined, counts))).toContain("First found by 20 Nov 2026 on slow.example");
    expect(isUncertain(first)).toBe(false);
  });

  it("explains when every result was blocked", () => {
    const s = buildSummary(model([]), undefined, { pending: 340, verified: 0, unrelated: 1, fetch_failed: 0, blocked: 48 });
    expect(text(s)).toContain("Google's redirect pages blocked 48 results");
    expect(s.facts).toEqual(["0 verified", "48 blocked", "340 not checked"]);
  });

  it("says plainly when nothing was found", () => {
    const s = buildSummary(model([]), undefined, { ...counts, verified: 0 });
    expect(text(s)).toBe("No verified copy of this picture was found.");
  });
});
