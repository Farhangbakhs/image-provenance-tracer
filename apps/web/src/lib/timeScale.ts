"use client";

import { scaleUtc } from "d3-scale";
import { useMemo, useRef, useState, type WheelEvent } from "react";

import type { SightingOut } from "./api/client";

const MIN_SPAN_MS = 60 * 60 * 1000; // zoom stops at one hour across the view

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

/**
 * A horizontal UTC time scale over a fixed-width SVG, zoomed by the mouse wheel around the
 * cursor (years down to an hour) and reset with `fit`.
 */
export function useZoomableTime(sightings: SightingOut[], range: [number, number], width: number) {
  const full = useMemo(() => timeExtent(sightings), [sightings]);
  const [domain, setDomain] = useState<[Date, Date]>(full);
  const svg = useRef<SVGSVGElement>(null);
  const x = scaleUtc().domain(domain).range(range);

  const onWheel = (event: WheelEvent<SVGSVGElement>) => {
    const box = svg.current?.getBoundingClientRect();
    if (!box) return;
    const px = ((event.clientX - box.left) / box.width) * width;
    const pivot = x.invert(Math.max(range[0], px)).getTime();
    const factor = event.deltaY > 0 ? 1.25 : 0.8;
    const [a, b] = domain.map((d) => d.getTime());
    let lo = pivot - (pivot - a) * factor;
    let hi = pivot + (b - pivot) * factor;
    if (hi - lo < MIN_SPAN_MS) [lo, hi] = [pivot - MIN_SPAN_MS / 2, pivot + MIN_SPAN_MS / 2];
    setDomain([new Date(lo), new Date(hi)]);
  };

  return { x, svg, onWheel, fit: () => setDomain(full), ticks: x.ticks(8), format: x.tickFormat(8) };
}
