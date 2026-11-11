import { describe, expect, it } from "vitest";

import { stageOrder } from "@/components/AssetPanel";

import { forwardLinks, postLabel } from "./VariantGraph";

describe("forwardLinks", () => {
  const analysis = {
    variants: [
      { id: "v1", label: "A", representative_sighting_id: "s1", sighting_ids: ["s1", "s2"] },
      { id: "v2", label: "B", representative_sighting_id: "s3", sighting_ids: ["s3"] },
    ],
    propagation: [
      { from_sighting_id: "s1", to_sighting_id: "s2", kind: "forward", reason: "r", evidence: {} },
      { from_sighting_id: "s2", to_sighting_id: "s3", kind: "forward", reason: "r", evidence: {} },
      { from_sighting_id: "s9", to_sighting_id: "s3", kind: "forward", reason: "r", evidence: {} },
    ],
  };
  const pages = {
    s1: "https://t.me/first_hand/7",
    s2: "https://t.me/demo_wire/40",
    s3: "https://news.example/story",
  };

  it("lists forwards inside a variant and draws the rest as edges", () => {
    const { inside, between } = forwardLinks(analysis, pages);
    expect(inside).toEqual({ v1: ["first_hand/7 → demo_wire/40"] });
    expect(between).toEqual([
      { source: "v1", target: "v2", label: "forward: demo_wire/40 → https://news.example/story" },
    ]);
  });

  it("labels posts compactly", () => {
    expect(postLabel("https://t.me/demo_wire/40?embed=1")).toBe("demo_wire/40");
    expect(postLabel(null)).toBe("?");
  });
});

describe("stageOrder", () => {
  it("shows the Telegram sweep after date only when the run reports it", () => {
    expect(stageOrder(["ingest"])).not.toContain("telegram_sweep");
    const order = stageOrder(["telegram_sweep"]);
    expect(order[order.indexOf("date") + 1]).toBe("telegram_sweep");
  });
});
