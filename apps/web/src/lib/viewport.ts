import { formatDay } from "./time";

export const DAY = 86_400_000;
/** The smallest window the timeline will show. */
export const MIN_SPAN = DAY;
/** Copies further apart than this start a new cluster when choosing the default view. */
const CLUSTER_GAP = 21 * DAY;

/** A window on the time axis: [start, end] in milliseconds since the epoch (UTC). */
export type View = [number, number];

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/**
 * Keep a window inside the full range, between one day and the whole range wide. When the width
 * has to change, the centre stays where it was.
 */
export function clampView(view: View, full: View, minSpan = MIN_SPAN): View {
  const max = full[1] - full[0];
  const span = Math.min(Math.max(view[1] - view[0], Math.min(minSpan, max)), max);
  const centre = (view[0] + view[1]) / 2;
  const lo = Math.min(Math.max(centre - span / 2, full[0]), full[1] - span);
  return [lo, lo + span];
}

/** Zoom by `factor` (above 1 zooms in) keeping the time under `anchor` where it is on screen. */
export function zoomAt(view: View, factor: number, anchor: number, full: View): View {
  const lo = anchor - (anchor - view[0]) / factor;
  const hi = anchor + (view[1] - anchor) / factor;
  return clampView([lo, hi], full);
}

/** Slide the window by `dt` milliseconds, without leaving the full range. */
export function panBy(view: View, dt: number, full: View): View {
  const span = view[1] - view[0];
  const lo = Math.min(Math.max(view[0] + dt, full[0]), full[1] - span);
  return [lo, lo + span];
}

/** A window around these times with a margin on both sides (10% by default). */
export function fitTimes(times: number[], full: View, pad = 0.1): View {
  if (times.length === 0) return full;
  const lo = Math.min(...times);
  const hi = Math.max(...times);
  const span = Math.max(hi - lo, MIN_SPAN);
  const mid = (lo + hi) / 2;
  const half = (span * (1 + 2 * pad)) / 2;
  return clampView([mid - half, mid + half], full);
}

/**
 * The view the page opens on, and "Reset view" returns to: the densest stretch of the range that
 * holds the earliest-found copy and the original story's first copy, with 10% around it.
 *
 * Copies are grouped into clusters, a gap of more than three weeks starting a new one. The window
 * starts as the clusters that hold the anchors and widens to the nearest cluster until it holds
 * at least half the copies, so a few copies proven only by today's fetch never stretch the axis
 * over years, and a view is never so narrow that most of the picture lies outside it.
 */
export function defaultView(times: number[], anchors: number[], full: View): View {
  const sorted = [...times].sort((a, b) => a - b);
  if (sorted.length === 0 || anchors.length === 0) return full;
  const clusters: View[] = [];
  for (const t of sorted) {
    const last = clusters[clusters.length - 1];
    if (last && t - last[1] <= CLUSTER_GAP) last[1] = t;
    else clusters.push([t, t]);
  }
  const holding = clusters.map((c, i) => ({ c, i })).filter(({ c }) => anchors.some((a) => a >= c[0] && a <= c[1]));
  if (holding.length === 0) return full;
  let lo = Math.min(...holding.map(({ i }) => i));
  let hi = Math.max(...holding.map(({ i }) => i));
  const inside = () => sorted.filter((t) => t >= clusters[lo][0] && t <= clusters[hi][1]).length;
  while (inside() < sorted.length / 2 && (lo > 0 || hi < clusters.length - 1)) {
    const left = lo > 0 ? clusters[lo][0] - clusters[lo - 1][1] : Infinity;
    const right = hi < clusters.length - 1 ? clusters[hi + 1][0] - clusters[hi][1] : Infinity;
    if (left <= right) lo -= 1;
    else hi += 1;
  }
  return fitTimes([clusters[lo][0], clusters[hi][1]], full);
}

/** How many of these copies fall outside the window. Undated copies are not counted. */
export function outsideCount(times: Array<number | null>, view: View): number {
  return times.filter((t) => t !== null && (t < view[0] || t > view[1])).length;
}

/** Copies per bin across the full range: the overview strip's histogram. */
export function histogram(times: number[], full: View, bins: number): number[] {
  const counts = new Array<number>(Math.max(1, bins)).fill(0);
  const span = full[1] - full[0];
  for (const t of times) {
    const i = Math.min(counts.length - 1, Math.max(0, Math.floor(((t - full[0]) / span) * counts.length)));
    counts[i] += 1;
  }
  return counts;
}

/** The window as a rectangle on a strip of this width. */
export function viewToWindow(view: View, full: View, width: number): { x: number; w: number } {
  const span = full[1] - full[0];
  return { x: ((view[0] - full[0]) / span) * width, w: ((view[1] - view[0]) / span) * width };
}

/** The inverse of {@link viewToWindow}. */
export function windowToView(x: number, w: number, full: View, width: number): View {
  const span = full[1] - full[0];
  const lo = full[0] + (x / width) * span;
  return [lo, lo + (w / width) * span];
}

/** The current range as short muted text: "Nov 2019 – Jan 2020", or days when it is short. */
export function formatRange(view: View): string {
  const [a, b] = [new Date(view[0]), new Date(view[1])];
  if (view[1] - view[0] <= 45 * DAY) {
    const [x, y] = [formatDay(a), formatDay(b)];
    return x === y ? x : `${x} – ${y}`;
  }
  const month = (d: Date) => `${MONTHS[d.getUTCMonth()]} ${d.getUTCFullYear()}`;
  const [x, y] = [month(a), month(b)];
  return x === y ? x : `${x} – ${y}`;
}

/** Ctrl or ⌘ with the wheel (a trackpad pinch arrives this way) zooms; a plain wheel scrolls. */
export function wheelIntent(event: { ctrlKey: boolean; metaKey: boolean; deltaY: number }): {
  zoom: boolean;
  factor: number;
} {
  if (!event.ctrlKey && !event.metaKey) return { zoom: false, factor: 1 };
  return { zoom: true, factor: Math.exp(-Math.max(-120, Math.min(120, event.deltaY)) * 0.0025) };
}

/** How long a programmatic change (reset, a bundle click) takes: none for reduced motion. */
export function animationMs(reducedMotion: boolean): number {
  return reducedMotion ? 0 : 250;
}

/** Ease-out cubic: fast first, settling at the end. */
export function easeOut(t: number): number {
  return 1 - Math.pow(1 - Math.min(1, Math.max(0, t)), 3);
}

export function tweenView(from: View, to: View, t: number): View {
  const e = easeOut(t);
  return [from[0] + (to[0] - from[0]) * e, from[1] + (to[1] - from[1]) * e];
}
