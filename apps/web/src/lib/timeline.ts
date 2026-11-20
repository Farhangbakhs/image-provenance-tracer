import { scaleUtc } from "d3-scale";

import type { SightingOut } from "./api/client";

export const DOT_R = 4;
export const FIRST_R = 6;
export const PILL_R = 11;
/** Clear space kept between two marks on a row: two dots are at least 16 px apart. */
export const GAP = 8;

const DAY = 86_400_000;
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** Where a copy is drawn: the earliest date its evidence allows, else the date it is proven by. */
export function placedTime(s: SightingOut): number | null {
  const v = s.date_lower ?? s.date_upper;
  return v ? new Date(v).getTime() : null;
}

/** A time window around these times, padded a little on both sides. */
export function fitDomain(times: number[], pad = 0.06): [number, number] {
  if (times.length === 0) {
    const now = Date.now();
    return [now - 7 * DAY, now];
  }
  const lo = Math.min(...times);
  const hi = Math.max(...times);
  if (hi === lo) return [lo - 3 * DAY, hi + 3 * DAY];
  const margin = (hi - lo) * pad;
  return [lo - margin, hi + margin];
}

export interface Tick {
  x: number;
  label: string;
}

const MIN_TICK_GAP = 70;

/** Ticks on a linear axis: years, then months, then days, never closer than 70 px. */
export function axisTicks(domain: [number, number], width: number): Tick[] {
  const scale = scaleUtc().domain([new Date(domain[0]), new Date(domain[1])]).range([0, width]);
  const span = (domain[1] - domain[0]) / DAY;
  const count = Math.max(2, Math.min(10, Math.floor(width / 90)));
  const ticks = scale.ticks(count).map((d) => {
    const day = d.getUTCDate();
    const month = MONTHS[d.getUTCMonth()];
    const year = d.getUTCFullYear();
    let label: string;
    if (span > 3 * 365) label = String(year);
    else if (span > 150) label = day === 1 ? `${month} ${year}` : `${day} ${month}`;
    else if (span <= 3) label = d.getUTCHours() === 0 ? `${day} ${month}` : `${String(d.getUTCHours()).padStart(2, "0")}:00`;
    else label = `${day} ${month}`;
    return { x: scale(d), label };
  });
  // d3 may return more ticks than asked for; keep each one clear of the last one kept.
  const kept: Tick[] = [];
  for (const tick of ticks) {
    if (kept.length === 0 || tick.x - kept[kept.length - 1].x >= MIN_TICK_GAP) kept.push(tick);
  }
  return kept;
}

export type Mark =
  | { kind: "dot"; id: string; x: number; r: number; first: boolean }
  | { kind: "pill"; ids: string[]; x: number; r: number };

interface Group {
  ids: string[];
  xs: number[];
  first: boolean;
}

const center = (g: Group) => g.xs.reduce((a, b) => a + b, 0) / g.xs.length;
const radius = (g: Group) => (g.ids.length > 1 ? PILL_R : g.first ? FIRST_R : DOT_R);

/**
 * Marks for one row. Copies that would touch merge into a pill showing their count, and pills
 * that would then touch merge again, so no two marks on a row ever overlap at any zoom.
 */
export function layoutRow(items: Array<{ id: string; x: number; first?: boolean }>, gap = GAP): Mark[] {
  const groups: Group[] = [...items]
    .sort((a, b) => a.x - b.x)
    .map((i) => ({ ids: [i.id], xs: [i.x], first: Boolean(i.first) }));
  for (let again = true; again; ) {
    again = false;
    for (let i = 0; i < groups.length - 1; i++) {
      const a = groups[i];
      const b = groups[i + 1];
      if (center(b) - center(a) < radius(a) + radius(b) + gap) {
        groups.splice(i, 2, { ids: [...a.ids, ...b.ids], xs: [...a.xs, ...b.xs], first: a.first || b.first });
        again = true;
        break;
      }
    }
  }
  return groups.map((g): Mark =>
    g.ids.length > 1
      ? { kind: "pill", ids: g.ids, x: center(g), r: PILL_R }
      : { kind: "dot", id: g.ids[0], x: g.xs[0], r: radius(g), first: g.first },
  );
}
