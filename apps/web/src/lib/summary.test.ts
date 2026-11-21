import { describe, expect, it } from "vitest";

import type { NarrativeOut, RunAnalysisOut, SightingOut } from "./api/client";
import { buildFacts, buildSummary, isUncertain, type RunSummary } from "./summary";
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

const first = sighting("s1", "www.valencia-news.example", "2024-10-30T07:40:00Z", "2024-10-30T08:15:00Z");
const second = sighting("s2", "iberia.example", "2024-11-04T10:00:00Z", "2024-11-05T12:00:00Z");
const third = sighting("s3", "viral.example", "2024-11-11T18:00:00Z", "2024-11-12T09:00:00Z");

describe("buildSummary", () => {
  it("names the first copy, its story in quotes, and how many stories contradict it", () => {
    const m = model([first, second, third], { s1: "root", s2: "root", s3: "b1" });
    const s = buildSummary(
      m,
      analysis([narrative("root", "Floods in Valencia", null), narrative("b1", "Hurricane Milton", "root")]),
      counts,
    );
    expect(text(s)).toBe(
      "First found 30 Oct 2024 on valencia-news.example, telling “Floods in Valencia”. Since reused in 1 other story, contradicting it.",
    );
  });

  it("never shows www. in a domain", () => {
    const s = buildSummary(model([first]), undefined, counts);
    expect(s.parts[1]).toEqual({ domain: "valencia-news.example", sightingId: "s1" });
  });

  it("says all of several retellings contradict it", () => {
    const m = model([first, second, third], { s1: "root" });
    const s = buildSummary(
      m,
      analysis([narrative("root", "Original", null), narrative("b1", "A", "root"), narrative("b2", "B", "root")]),
      counts,
    );
    expect(text(s)).toContain("Since reused in 2 other stories, all contradicting it.");
  });

  it("with no narratives says no captions could be read", () => {
    const s = buildSummary(model([first, second]), analysis([]), counts);
    expect(text(s)).toBe("First found 30 Oct 2024 on valencia-news.example. No captions could be read from the copies checked.");
  });

  it("with one narrative says no retellings were found", () => {
    const m = model([first, second], { s1: "root" });
    const s = buildSummary(m, analysis([narrative("root", "Floods in Valencia", null)]), counts);
    expect(text(s)).toBe(
      "First found 30 Oct 2024 on valencia-news.example, telling “Floods in Valencia”. No retellings found among the copies checked.",
    );
  });

  it("with a single sighting says it is the only copy", () => {
    const s = buildSummary(model([first]), analysis([]), { ...counts, verified: 1 });
    expect(text(s)).toBe("First found 30 Oct 2024 on valencia-news.example. It is the only verified copy.");
  });

  it("splits the first copy from the earliest readable story when the first caption is unreadable", () => {
    const m = model([first, second, third], { s2: "root", s3: "b1" });
    const s = buildSummary(
      m,
      analysis([narrative("root", "Floods in Valencia", null), narrative("b1", "Hurricane Milton", "root")]),
      counts,
    );
    expect(text(s)).toBe(
      "First found 30 Oct 2024 on valencia-news.example (caption unreadable). " +
        "Earliest readable story: “Floods in Valencia” on iberia.example, 5 Nov 2024. " +
        "Since reused in 1 other story, contradicting it.",
    );
    // Both domains select their own copy.
    expect(s.parts.filter((p) => "domain" in p)).toEqual([
      { domain: "valencia-news.example", sightingId: "s1" },
      { domain: "iberia.example", sightingId: "s2" },
    ]);
  });

  it("keeps a story name exactly as stored", () => {
    const m = model([first, second], { s1: "root" });
    const label = "Israeli attack in Jan Yunis, Gaza";
    expect(text(buildSummary(m, analysis([narrative("root", label, null)]), counts))).toContain(`“${label}”`);
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
    expect(s.facts).toEqual(["0 verified", "1 not matched", "48 blocked", "340 not checked"]);
  });

  it("says plainly when nothing was found", () => {
    const s = buildSummary(model([]), undefined, { ...counts, verified: 0 });
    expect(text(s)).toBe("No verified copy of this picture was found.");
  });
});

describe("buildFacts", () => {
  it("reports the stored counts, with blocked shown even at zero", () => {
    expect(buildFacts({ pending: 349, verified: 29, unrelated: 11, fetch_failed: 10, blocked: 0 })).toEqual([
      "29 verified",
      "21 not matched",
      "0 blocked",
      "349 not checked",
    ]);
  });
});
