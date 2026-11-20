import { describe, expect, it } from "vitest";

import type { NarrativeOut, RunAnalysisOut, SightingOut } from "./api/client";
import { buildStories, copyCount, MAX_ROWS } from "./stories";
import { NO_CLAIM_LANE, type WorkspaceModel } from "./workspace";

const sighting = (id: string, upper: string | null): SightingOut =>
  ({ id, domain: `${id}.example`, date_lower: upper, date_upper: upper }) as unknown as SightingOut;

const narrative = (id: string, label: string, parent: string | null): NarrativeOut =>
  ({
    id,
    label,
    summary: `${label} summary`,
    parent_narrative_id: parent,
    divergence_reason: parent ? "contradicts the place" : null,
    claim_ids: [],
    divergence_sighting_id: "x",
  }) as unknown as NarrativeOut;

function setup(spec: Array<[string, string | null, string]>, narratives: NarrativeOut[]) {
  const sightings = spec.map(([id, date]) => sighting(id, date));
  const laneOf = Object.fromEntries(spec.map(([id, , lane]) => [id, lane]));
  const model: WorkspaceModel = { sightings, earliestId: null, lanes: [], laneOf, divergenceOf: {}, variantLabel: {} };
  return { model, analysis: { narratives } as unknown as RunAnalysisOut };
}

describe("buildStories", () => {
  it("puts the original first, then stories by the date of their first copy", () => {
    const { model, analysis } = setup(
      [
        ["a", "2019-12-20T00:00:00Z", "late"],
        ["b", "2019-12-01T00:00:00Z", "early"],
        ["c", "2019-11-15T00:00:00Z", "root"],
        ["d", "2019-12-05T00:00:00Z", "early"],
      ],
      [narrative("late", "Late", "root"), narrative("root", "Original", null), narrative("early", "Early", "root")],
    );
    const stories = buildStories(model, analysis);
    expect(stories.rows.map((r) => r.id)).toEqual(["root", "early", "late"]);
    expect(stories.rows.map((r) => r.status)).toEqual(["Original story", "Contradicts original", "Contradicts original"]);
    expect(stories.rows[1].copies.map((s) => s.id)).toEqual(["b", "d"]);
    expect(stories.rows[1].first?.id).toBe("b");
    expect(stories.rows[1].reason).toBe("contradicts the place");
  });

  it("shows six stories and counts the rest", () => {
    const narratives = [narrative("r", "Original", null), ...Array.from({ length: 8 }, (_, i) => narrative(`n${i}`, `Story ${i}`, "r"))];
    const spec: Array<[string, string, string]> = narratives.map((n, i) => [`s${i}`, `2020-01-${String(i + 1).padStart(2, "0")}T00:00:00Z`, n.id]);
    const { model, analysis } = setup(spec, narratives);
    const stories = buildStories(model, analysis);
    expect(stories.shown).toHaveLength(MAX_ROWS);
    expect(stories.hidden).toBe(3);
    expect(buildStories(model, analysis, true).hidden).toBe(0);
  });

  it("collects copies with no readable caption, oldest first", () => {
    const { model, analysis } = setup(
      [
        ["x", "2020-02-01T00:00:00Z", NO_CLAIM_LANE],
        ["y", "2020-01-01T00:00:00Z", NO_CLAIM_LANE],
        ["z", "2019-11-01T00:00:00Z", "root"],
      ],
      [narrative("root", "Original", null)],
    );
    expect(buildStories(model, analysis).uncaptioned.map((s) => s.id)).toEqual(["y", "x"]);
  });

  it("with no narratives has no story rows, only uncaptioned copies", () => {
    const { model } = setup([["x", "2020-02-01T00:00:00Z", NO_CLAIM_LANE]], []);
    const stories = buildStories(model, undefined);
    expect(stories.rows).toEqual([]);
    expect(stories.uncaptioned).toHaveLength(1);
  });

  it("puts a story whose first copy has no date last", () => {
    const { model, analysis } = setup(
      [
        ["a", null, "undated"],
        ["b", "2020-01-01T00:00:00Z", "dated"],
        ["r", "2019-01-01T00:00:00Z", "root"],
      ],
      [narrative("undated", "Undated", "root"), narrative("dated", "Dated", "root"), narrative("root", "Original", null)],
    );
    expect(buildStories(model, analysis).rows.map((r) => r.id)).toEqual(["root", "dated", "undated"]);
  });
});

describe("copyCount", () => {
  it("pluralises", () => {
    expect(copyCount(1)).toBe("1 copy");
    expect(copyCount(3)).toBe("3 copies");
  });
});
