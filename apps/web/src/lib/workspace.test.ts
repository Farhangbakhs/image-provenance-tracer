import { describe, expect, it } from "vitest";

import type { RunAnalysisOut, RunSightingsOut, SightingOut } from "./api/client";
import { NO_CLAIM_LANE, buildWorkspace, step } from "./workspace";
import { buildLineageGraph, groupDays, lineageRows, neighbourhood } from "./lineage-graph";
import { stageOrder } from "@/components/AssetPanel";

import { explainDate, explainGrade, explainMatch } from "./explain";

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

describe("lineageRows", () => {
  it("orders variants by their earliest copy and says what each was derived from", () => {
    const model = buildWorkspace(sightings, undefined);
    const rows = lineageRows(model, {
      run_id: "r",
      variants: [
        { id: "v2", label: "V2", representative_sighting_id: "c", sighting_ids: ["c"] },
        { id: "v1", label: "V1", representative_sighting_id: "a", sighting_ids: ["b", "a"] },
      ],
      edges: [{ parent_variant_id: "v1", child_variant_id: "v2", kind: "crop", reason: "r", evidence: {} }],
      propagation: [],
      claims: [],
      narratives: [],
      grades: [],
      notes: {},
    });
    expect(rows.map((r) => r.label)).toEqual(["V1", "V2"]);
    expect(rows[0].first?.id).toBe("a");
    expect(rows[0].derivedFrom).toBeNull();
    expect(rows[1].derivedFrom).toBe("cropped from V1");
  });
});

describe("buildLineageGraph", () => {
  const analysis = {
    run_id: "r",
    variants: [
      { id: "v1", label: "V1", representative_sighting_id: "a", sighting_ids: ["a", "b"] },
      { id: "v2", label: "V2", representative_sighting_id: "c", sighting_ids: ["c"] },
    ],
    edges: [{ parent_variant_id: "v1", child_variant_id: "v2", kind: "mirror", reason: "r", evidence: {} }],
    propagation: [{ from_sighting_id: "a", to_sighting_id: "b", kind: "forward", reason: "r", evidence: {} }],
    claims: [],
    narratives: [],
    grades: [],
    notes: {},
  };

  it("places copies left to right in time and links them", () => {
    const graph = buildLineageGraph(buildWorkspace(sightings, undefined), analysis);
    const x = Object.fromEntries(graph.nodes.map((n) => [n.id, n.timeX]));
    expect(x.a).toBeLessThan(x.b);
    expect(x.b).toBeLessThan(x.c);
    expect(graph.nodes.find((n) => n.id === "a")?.earliest).toBe(true);
    expect(graph.nodes.find((n) => n.id === "c")?.laneY).toBeGreaterThan(0);
    expect(graph.links.map((l) => `${l.source}>${l.target}:${l.kind}`)).toEqual(["a>b:same", "a>c:mirror", "a>b:forward"]);
    expect(graph.links.find((l) => l.kind === "mirror")?.label).toBe("mirrored");
    expect(graph.days.map((d) => d.day)).toEqual(["2024-10-30", "2024-11-05", "2024-11-20"]);
  });

  it("groups busy runs' date chips by month, then by year", () => {
    const days = Array.from({ length: 14 }, (_, i) => ({ day: `2024-${String((i % 7) + 1).padStart(2, "0")}-0${(i % 3) + 1}`, ids: [`s${i}`] }));
    const months = groupDays(days);
    expect(months.map((d) => d.day)).toEqual(["2024-01", "2024-02", "2024-03", "2024-04", "2024-05", "2024-06", "2024-07"]);
    expect(months[0].ids).toEqual(["s0", "s7"]);
    expect(groupDays(days.slice(0, 3)).map((d) => d.day)).toEqual(["2024-01-01", "2024-02-02", "2024-03-03"]);
  });

  it("lights up a node and its neighbours", () => {
    const graph = buildLineageGraph(buildWorkspace(sightings, undefined), analysis);
    expect([...neighbourhood(graph.links, "c")].sort()).toEqual(["a", "c"]);
  });
});

describe("explanations", () => {
  const s = (over: Partial<SightingOut>): SightingOut => ({ ...sighting("x", "2024-01-02T00:00:00Z"), ...over }) as SightingOut;

  it("describes the match in words", () => {
    expect(explainMatch(s({ match_class: "exact" }))).toBe("Identical file to yours.");
    expect(explainMatch(s({ match_class: "derivative", transform: { edits: ["crop", "overlay"] } }))).toBe(
      "Edited copy: cropped, text or graphics added.",
    );
  });

  it("says what dated the copy", () => {
    const deciding = { id: "e", kind: "wayback_page", value: "", bound: "no_later_than", confidence: "medium", source_url: null, detail: {} };
    expect(explainDate(s({ date_lower: null, deciding }))).toBe("Online by 2024-01-02 (archive capture of the page).");
    expect(explainDate(s({ date_lower: "2024-01-02T00:00:00Z", deciding: { ...deciding, kind: "platform", bound: "exact" } }))).toBe(
      "Posted 2024-01-02 (platform timestamp).",
    );
  });

  it("reads the Admiralty grades", () => {
    expect(explainGrade(s({ reliability: "F", credibility: 4 }))).toBe("Source not yet graded (F); credibility 4 of 6.");
  });
});

describe("stageOrder", () => {
  it("shows the Telegram sweep after date only when the run reports it", () => {
    expect(stageOrder(["ingest"])).not.toContain("telegram_sweep");
    const order = stageOrder(["telegram_sweep"]);
    expect(order[order.indexOf("date") + 1]).toBe("telegram_sweep");
  });
});
