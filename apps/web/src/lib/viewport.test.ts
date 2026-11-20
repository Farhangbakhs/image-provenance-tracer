import { describe, expect, it } from "vitest";

import { fitDomain, GAP, layoutRow } from "./timeline";
import {
  animationMs,
  clampView,
  DAY,
  defaultView,
  easeOut,
  fitTimes,
  formatRange,
  histogram,
  outsideCount,
  panBy,
  tweenView,
  viewToWindow,
  wheelIntent,
  windowToView,
  zoomAt,
  type View,
} from "./viewport";

const d = (y: number, m: number, day: number) => Date.UTC(y, m - 1, day);

// The shape of a real trace: a first burst in Nov 2019, a bigger one on 8 Jan 2020, a tail to Mar 2020,
// then stragglers up to a 2026 fetch.
const times = [
  d(2016, 1, 20),
  d(2019, 11, 15),
  d(2019, 11, 15) + 3_600_000,
  d(2019, 11, 16),
  d(2019, 11, 16) + 7_200_000,
  d(2019, 11, 27),
  d(2020, 1, 7),
  ...Array.from({ length: 8 }, (_, i) => d(2020, 1, 8) + i * 3_600_000),
  d(2020, 1, 31),
  d(2020, 2, 14),
  d(2020, 3, 1),
  d(2020, 11, 14),
  d(2021, 8, 22),
  d(2026, 11, 19),
  d(2026, 11, 20),
];
const full = fitDomain(times);

describe("defaultView", () => {
  it("fits the dense period holding the earliest and the original's first copy, not the whole range", () => {
    const earliest = d(2019, 11, 15);
    const view = defaultView(times, [earliest, d(2019, 11, 16)], full);
    expect(view[0]).toBeLessThanOrEqual(earliest);
    expect(view[1]).toBeGreaterThanOrEqual(d(2020, 1, 8));
    expect(view[1]).toBeLessThan(d(2020, 3, 1)); // not the tail, and not the stragglers into 2026
    expect(formatRange(view)).toMatch(/^Nov 2019 – Jan 2020$/);
  });

  it("always contains the earliest copy and the original's first copy", () => {
    for (const anchors of [[d(2019, 11, 15)], [d(2019, 11, 15), d(2026, 11, 19)], [d(2026, 11, 20)]]) {
      const view = defaultView(times, anchors, full);
      for (const a of anchors) {
        expect(a).toBeGreaterThanOrEqual(view[0]);
        expect(a).toBeLessThanOrEqual(view[1]);
      }
    }
  });

  it("spans both clusters when the anchors lie in different ones", () => {
    const view = defaultView(times, [d(2019, 11, 15), d(2026, 11, 19)], full);
    expect(view[0]).toBeLessThanOrEqual(d(2019, 11, 15));
    expect(view[1]).toBeGreaterThanOrEqual(d(2026, 11, 19));
  });

  it("falls back to the full range without copies or anchors", () => {
    expect(defaultView([], [], full)).toEqual(full);
    expect(defaultView(times, [], full)).toEqual(full);
  });
});

describe("limits", () => {
  it("never goes below one day or past the full range", () => {
    const tiny = clampView([d(2019, 11, 15), d(2019, 11, 15) + 1000], full);
    expect(tiny[1] - tiny[0]).toBe(DAY);
    const huge = clampView([full[0] - 10 * DAY, full[1] + 10 * DAY], full);
    expect(huge).toEqual(full);
    const off = clampView([full[1] - DAY, full[1] + 9 * DAY], full);
    expect(off[1]).toBeLessThanOrEqual(full[1]);
    expect(off[0]).toBeGreaterThanOrEqual(full[0]);
  });

  it("zooms around the cursor: the time under it stays put", () => {
    const view: View = [d(2019, 11, 1), d(2020, 1, 31)];
    const anchor = d(2019, 12, 10);
    const frac = (anchor - view[0]) / (view[1] - view[0]);
    const zoomed = zoomAt(view, 4, anchor, full);
    expect(zoomed[1] - zoomed[0]).toBeCloseTo((view[1] - view[0]) / 4, 0);
    expect((anchor - zoomed[0]) / (zoomed[1] - zoomed[0])).toBeCloseTo(frac, 6);
  });

  it("stops zooming in at one day and out at the full range", () => {
    let view: View = [d(2019, 11, 1), d(2019, 12, 1)];
    for (let i = 0; i < 30; i++) view = zoomAt(view, 2, d(2019, 11, 10), full);
    expect(view[1] - view[0]).toBe(DAY);
    for (let i = 0; i < 40; i++) view = zoomAt(view, 0.5, d(2019, 11, 10), full);
    expect(view).toEqual(full);
  });

  it("pans without leaving the range", () => {
    const view: View = [d(2019, 11, 1), d(2019, 12, 1)];
    expect(panBy(view, -9999 * DAY, full)[0]).toBe(full[0]);
    expect(panBy(view, 9999 * DAY, full)[1]).toBe(full[1]);
    expect(panBy(view, 5 * DAY, full)).toEqual([view[0] + 5 * DAY, view[1] + 5 * DAY]);
  });
});

describe("fitTimes", () => {
  it("pads 10% each side and holds a one-day minimum for copies on one day", () => {
    const [lo, hi] = fitTimes([d(2019, 11, 15), d(2019, 11, 25)], full);
    expect(d(2019, 11, 15) - lo).toBeCloseTo(DAY, 0);
    expect(hi - d(2019, 11, 25)).toBeCloseTo(DAY, 0);
    const [a, b] = fitTimes([d(2019, 11, 15), d(2019, 11, 15) + 60_000], full);
    expect(b - a).toBeGreaterThanOrEqual(DAY);
  });
});

describe("the overview and the main view stay in sync", () => {
  it("maps a view to the strip and back without drift", () => {
    for (const view of [defaultView(times, [d(2019, 11, 15)], full), [d(2019, 12, 1), d(2019, 12, 9)] as View, full]) {
      for (const width of [300, 900, 1500]) {
        const { x, w } = viewToWindow(view, full, width);
        const back = windowToView(x, w, full, width);
        expect(back[0]).toBeCloseTo(view[0], 0);
        expect(back[1]).toBeCloseTo(view[1], 0);
      }
    }
  });

  it("the full range is the whole strip", () => {
    expect(viewToWindow(full, full, 600)).toEqual({ x: 0, w: 600 });
  });

  it("bins every copy exactly once", () => {
    const bins = histogram(times, full, 40);
    expect(bins).toHaveLength(40);
    expect(bins.reduce((a, b) => a + b, 0)).toBe(times.length);
  });
});

describe("outsideCount", () => {
  it("counts copies outside the window and ignores undated ones", () => {
    const view: View = [d(2019, 11, 1), d(2019, 12, 31)];
    expect(outsideCount([d(2019, 11, 15), d(2020, 1, 10), d(2026, 11, 19), null], view)).toBe(2);
  });
});

describe("no overlap at any zoom", () => {
  it("keeps dots and pills 16 px apart at five zoom levels", () => {
    const width = 900;
    const copies = Array.from({ length: 60 }, (_, i) => d(2019, 11, 15) + i * 0.6 * DAY + (i % 7) * 3_600_000);
    const all = fitDomain(copies);
    const spans = [1, 1 / 4, 1 / 16, 1 / 64, 1 / 512].map((f) => Math.max(DAY, (all[1] - all[0]) * f));
    for (const span of spans) {
      const view = clampView([d(2019, 11, 15), d(2019, 11, 15) + span], all);
      const items = copies
        .filter((t) => t >= view[0] && t <= view[1])
        .map((t, i) => ({ id: `s${i}`, x: ((t - view[0]) / (view[1] - view[0])) * width, first: i === 0 }));
      const marks = layoutRow(items);
      expect(marks.flatMap((m) => (m.kind === "pill" ? m.ids : [m.id]))).toHaveLength(items.length);
      for (let i = 1; i < marks.length; i++) {
        const gap = marks[i].x - marks[i - 1].x;
        expect(gap).toBeGreaterThanOrEqual(16);
        expect(gap).toBeGreaterThanOrEqual(marks[i].r + marks[i - 1].r + GAP - 1e-9);
      }
    }
  });

  it("splits a bundle into separate dots once zoomed in far enough", () => {
    const base = d(2019, 11, 15);
    const three = [0, 1, 2].map((i) => base + i * 8 * 3_600_000);
    const at = (span: number) => {
      const view: View = [base - span * 0.1, base + 16 * 3_600_000 + span * 0.1];
      return layoutRow(three.map((t, i) => ({ id: `s${i}`, x: ((t - view[0]) / (view[1] - view[0])) * 900 }))).length;
    };
    const wide = layoutRow(three.map((t, i) => ({ id: `s${i}`, x: ((t - (base - 60 * DAY)) / (120 * DAY)) * 900 })));
    expect(wide).toHaveLength(1); // a "3" bundle at the default zoom
    expect(at(DAY)).toBe(3); // three dots when zoomed to the day
  });
});

describe("wheel, motion and easing", () => {
  it("a plain wheel scrolls the page; Ctrl or ⌘ zooms", () => {
    expect(wheelIntent({ ctrlKey: false, metaKey: false, deltaY: 100 }).zoom).toBe(false);
    const out = wheelIntent({ ctrlKey: true, metaKey: false, deltaY: 100 });
    expect(out.zoom).toBe(true);
    expect(out.factor).toBeLessThan(1); // scrolling down zooms out
    expect(wheelIntent({ ctrlKey: false, metaKey: true, deltaY: -100 }).factor).toBeGreaterThan(1);
  });

  it("reduced motion removes the animation", () => {
    expect(animationMs(true)).toBe(0);
    expect(animationMs(false)).toBe(250);
  });

  it("eases out and lands exactly on the target", () => {
    expect(easeOut(0)).toBe(0);
    expect(easeOut(1)).toBe(1);
    expect(easeOut(0.5)).toBeGreaterThan(0.5);
    expect(tweenView([0, 10], [100, 200], 1)).toEqual([100, 200]);
    expect(tweenView([0, 10], [100, 200], 0)).toEqual([0, 10]);
  });
});

describe("formatRange", () => {
  it("shows months for long ranges and days for short ones", () => {
    expect(formatRange([d(2019, 11, 3), d(2020, 1, 20)])).toBe("Nov 2019 – Jan 2020");
    expect(formatRange([d(2019, 11, 3), d(2019, 11, 28)])).toBe("3 Nov 2019 – 28 Nov 2019");
    expect(formatRange([d(2019, 11, 3), d(2019, 11, 3) + 3600_000])).toBe("3 Nov 2019");
  });
});
