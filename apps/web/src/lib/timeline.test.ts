import { describe, expect, it } from "vitest";

import type { SightingOut } from "./api/client";
import { axisTicks, fitDomain, layoutRow, placedTime, type Mark } from "./timeline";

const at = (lower: string | null, upper: string | null) => ({ date_lower: lower, date_upper: upper }) as SightingOut;

describe("placedTime", () => {
  it("uses the earliest date the evidence allows, else the proven date", () => {
    expect(placedTime(at("2019-11-15T00:00:00Z", "2020-01-01T00:00:00Z"))).toBe(Date.UTC(2019, 10, 15));
    expect(placedTime(at(null, "2020-01-01T00:00:00Z"))).toBe(Date.UTC(2020, 0, 1));
    expect(placedTime(at(null, null))).toBeNull();
  });
});

describe("fitDomain", () => {
  it("pads both ends and handles one point or none", () => {
    const [lo, hi] = fitDomain([1000 * 86_400_000, 1010 * 86_400_000]);
    expect(lo).toBeLessThan(1000 * 86_400_000);
    expect(hi).toBeGreaterThan(1010 * 86_400_000);
    const [a, b] = fitDomain([5 * 86_400_000]);
    expect(a).toBeLessThan(5 * 86_400_000);
    expect(b).toBeGreaterThan(5 * 86_400_000);
    expect(fitDomain([])[1]).toBeGreaterThan(fitDomain([])[0]);
  });
});

describe("axisTicks", () => {
  it("labels years for long spans and days for short ones, and keeps them apart", () => {
    const years = axisTicks([Date.UTC(2014, 0, 1), Date.UTC(2026, 0, 1)], 900);
    expect(years.every((t) => /^\d{4}$/.test(t.label))).toBe(true);
    const days = axisTicks([Date.UTC(2019, 10, 1), Date.UTC(2019, 10, 20)], 900);
    expect(days.some((t) => /^\d+ Nov$/.test(t.label))).toBe(true);
    for (const ticks of [years, days]) {
      for (let i = 1; i < ticks.length; i++) expect(ticks[i].x - ticks[i - 1].x).toBeGreaterThanOrEqual(70);
    }
  });
});

function noOverlap(marks: Mark[], gap = 4) {
  for (let i = 1; i < marks.length; i++) {
    expect(marks[i].x - marks[i - 1].x).toBeGreaterThanOrEqual(marks[i].r + marks[i - 1].r + gap - 1e-9);
  }
}

describe("layoutRow", () => {
  it("keeps well separated copies as dots", () => {
    const marks = layoutRow([
      { id: "a", x: 10 },
      { id: "b", x: 100 },
      { id: "c", x: 200 },
    ]);
    expect(marks.map((m) => m.kind)).toEqual(["dot", "dot", "dot"]);
  });

  it("merges copies that would touch into a pill with all their ids", () => {
    const marks = layoutRow([
      { id: "a", x: 100 },
      { id: "b", x: 104 },
      { id: "c", x: 108 },
      { id: "d", x: 400 },
    ]);
    expect(marks).toHaveLength(2);
    expect(marks[0]).toMatchObject({ kind: "pill", ids: ["a", "b", "c"] });
    expect(marks[1]).toMatchObject({ kind: "dot", id: "d" });
  });

  it("merges pills that would touch each other, so nothing overlaps", () => {
    // Two clumps whose pills (radius 11) would overlap although the clumps are 30 px apart.
    const marks = layoutRow([
      { id: "a", x: 100 },
      { id: "b", x: 102 },
      { id: "c", x: 130 },
      { id: "d", x: 132 },
    ]);
    noOverlap(marks);
    expect(marks.flatMap((m) => (m.kind === "pill" ? m.ids : [m.id])).sort()).toEqual(["a", "b", "c", "d"]);
  });

  it("never overlaps and never loses a copy, at any density", () => {
    let seed = 7;
    const rand = () => {
      seed = (seed * 1664525 + 1013904223) % 4294967296;
      return seed / 4294967296;
    };
    for (const n of [1, 5, 40, 200]) {
      for (const width of [300, 900, 2400]) {
        const items = Array.from({ length: n }, (_, i) => ({ id: `s${i}`, x: rand() * width, first: i === 0 }));
        const marks = layoutRow(items);
        noOverlap(marks);
        const ids = marks.flatMap((m) => (m.kind === "pill" ? m.ids : [m.id]));
        expect(new Set(ids).size).toBe(n);
        expect(ids).toHaveLength(n);
      }
    }
  });

  it("gives the first copy of a story a larger dot", () => {
    const [mark] = layoutRow([{ id: "a", x: 10, first: true }]);
    expect(mark).toMatchObject({ kind: "dot", first: true, r: 6 });
  });
});
