import type { SightingOut } from "./api/client";

/** The time range covering every sighting's bounds, padded a little on both sides. */
export function timeExtent(sightings: SightingOut[]): [Date, Date] {
  const times = sightings.flatMap((s) =>
    [s.date_lower, s.date_upper].filter((v): v is string => Boolean(v)).map((v) => new Date(v).getTime()),
  );
  if (times.length === 0) {
    const now = Date.now();
    return [new Date(now - 86_400_000), new Date(now)];
  }
  const lo = Math.min(...times);
  const hi = Math.max(...times);
  const pad = Math.max((hi - lo) * 0.06, 6 * 3_600_000);
  return [new Date(lo - pad), new Date(hi + pad)];
}
