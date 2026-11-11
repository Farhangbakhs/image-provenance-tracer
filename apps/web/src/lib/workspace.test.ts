import { describe, expect, it } from "vitest";

import type { RunAnalysisOut, RunSightingsOut, SightingOut } from "./api/client";
import { NO_CLAIM_LANE, buildWorkspace, step } from "./workspace";
import { layoutTree } from "@/components/workspace/VariantGraph";

const sighting = (id: string, upper: string): SightingOut =>
  ({ id, date_upper: upper, date_lower: null, date_confidence: "high", domain: `${id}.example` }) as SightingOut;

const sightings: RunSightingsOut = {
  run_id: "r",
  status: "succeeded",
  earliest_sighting_id: "a",
  candidates: { pending: 0, verified: 3, unrelated: 0, fetch_failed: 0 },
  notes: {},
  sightings: [sighting("a", "2024-10-30T00:00:00Z"), sighting("b", "2024-11-05T00:00:00Z"), sighting("c", "2024-11-20T00:00:00Z")],
};

const analysis = {
  run_id: "r",
  variants: [{ id: "v1", label: "V1", representative_sighting_id: "a", sighting_ids: ["a", "b"] }],
  edges: [],
  claims: [
    { id: "c1", sighting_id: "a" },
    { id: "c2", sighting_id: "c" },
  ],
  narratives: [
    { id: "n2", label: "Florida", parent_narrative_id: "n1", divergence_sighting_id: "c", claim_ids: ["c2"] },
    { id: "n1", label: "Valencia", parent_narrative_id: null, divergence_sighting_id: "a", claim_ids: ["c1"] },
  ],
  grades: [],
  notes: {},
} as unknown as RunAnalysisOut;

describe("buildWorkspace", () => {
  it("puts the root narrative first, branches after, and unread pages in their own lane", () => {
    const model = buildWorkspace(sightings, analysis);
    expect(model.lanes.map((l) => [l.id, l.root])).toEqual([
      ["n1", true],
      ["n2", false],
      [NO_CLAIM_LANE, false],
    ]);
    expect(model.laneOf).toEqual({ a: "n1", b: NO_CLAIM_LANE, c: "n2" });
    expect(model.divergenceOf).toEqual({ n2: "c", n1: "a" });
    expect(model.variantLabel).toEqual({ a: "V1", b: "V1" });
  });

  it("works before any branching analysis exists", () => {
    const model = buildWorkspace(sightings, undefined);
    expect(model.lanes).toEqual([{ id: NO_CLAIM_LANE, label: "Sightings", root: false }]);
  });
});

describe("step", () => {
  it("moves and wraps", () => {
    expect(step(["a", "b", "c"], null, 1)).toBe("a");
    expect(step(["a", "b", "c"], "c", 1)).toBe("a");
    expect(step(["a", "b", "c"], "a", -1)).toBe("c");
    expect(step([], "a", 1)).toBeNull();
  });
});

describe("layoutTree", () => {
  it("places parents above and centred over their children", () => {
    const pos = layoutTree(["root", "x", "y", "lone"], { x: "root", y: "root" });
    expect(pos.root.y).toBe(0);
    expect(pos.x.y).toBe(170);
    expect(pos.root.x).toBe((pos.x.x + pos.y.x) / 2);
    expect(pos.lone.y).toBe(0);
  });
});
