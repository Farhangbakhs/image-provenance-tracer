"use client";

import { scaleUtc } from "d3-scale";
import { useMemo, useRef, useState, type WheelEvent } from "react";

import { CONFIDENCE_COLOUR, type WorkspaceModel } from "@/lib/workspace";
import { formatInterval } from "@/lib/time";

const LANE_HEIGHT = 56;
const LABEL_WIDTH = 168;
const AXIS_HEIGHT = 28;
const WIDTH = 960;
const MIN_SPAN_MS = 60 * 60 * 1000; // zoom stops at one hour across the view

function extent(model: WorkspaceModel): [Date, Date] {
  const times = model.sightings.flatMap((s) =>
    [s.date_lower, s.date_upper].filter((v): v is string => Boolean(v)).map((v) => new Date(v).getTime()),
  );
  if (times.length === 0) {
    const now = Date.now();
    return [new Date(now - 86_400_000), new Date(now)];
  }
  const lo = Math.min(...times);
  const hi = Math.max(...times);
  const pad = Math.max((hi - lo) * 0.08, 6 * 3_600_000);
  return [new Date(lo - pad), new Date(hi + pad)];
}

/**
 * One marker per sighting at its proven upper bound ("existed no later than"), with a band back
 * to its lower bound when one is known. Lanes are narratives; the earliest found is pinned in
 * amber. Scroll to zoom around the cursor, from years down to an hour.
 */
export function Timeline({
  model,
  selected,
  onSelect,
}: {
  model: WorkspaceModel;
  selected: string | null;
  onSelect: (id: string) => void;
}) {
  const full = useMemo(() => extent(model), [model]);
  const [domain, setDomain] = useState<[Date, Date]>(full);
  const svg = useRef<SVGSVGElement>(null);
  const x = scaleUtc().domain(domain).range([LABEL_WIDTH, WIDTH - 16]);
  const height = AXIS_HEIGHT + model.lanes.length * LANE_HEIGHT;
  const laneIndex = Object.fromEntries(model.lanes.map((lane, i) => [lane.id, i]));

  const onWheel = (event: WheelEvent<SVGSVGElement>) => {
    const box = svg.current?.getBoundingClientRect();
    if (!box) return;
    const px = ((event.clientX - box.left) / box.width) * WIDTH;
    const pivot = x.invert(Math.max(LABEL_WIDTH, px)).getTime();
    const factor = event.deltaY > 0 ? 1.25 : 0.8;
    const [a, b] = domain.map((d) => d.getTime());
    let lo = pivot - (pivot - a) * factor;
    let hi = pivot + (b - pivot) * factor;
    if (hi - lo < MIN_SPAN_MS) [lo, hi] = [pivot - MIN_SPAN_MS / 2, pivot + MIN_SPAN_MS / 2];
    setDomain([new Date(lo), new Date(hi)]);
  };

  const ticks = x.ticks(8);
  const format = x.tickFormat(8);

  return (
    <div>
      <div className="flex items-center justify-between px-3 py-1.5 text-[11px] text-muted">
        <span>Scroll over the chart to zoom. Bars run from the earliest possible to the proven date.</span>
        <button type="button" onClick={() => setDomain(full)} className="border border-line px-2 py-0.5 hover:border-text">
          Fit all
        </button>
      </div>
      <svg
        ref={svg}
        viewBox={`0 0 ${WIDTH} ${height}`}
        className="block w-full select-none"
        role="img"
        aria-label="Timeline of sightings by narrative"
        onWheel={onWheel}
      >
        {ticks.map((t) => (
          <g key={t.getTime()}>
            <line x1={x(t)} x2={x(t)} y1={AXIS_HEIGHT - 4} y2={height} stroke="var(--line)" />
            <text x={x(t)} y={16} textAnchor="middle" className="mono" fontSize={10} fill="var(--muted)">
              {format(t)}
            </text>
          </g>
        ))}
        {model.lanes.map((lane, i) => (
          <g key={lane.id}>
            <line x1={0} x2={WIDTH} y1={AXIS_HEIGHT + i * LANE_HEIGHT} y2={AXIS_HEIGHT + i * LANE_HEIGHT} stroke="var(--line)" />
            <text x={8} y={AXIS_HEIGHT + i * LANE_HEIGHT + 20} fontSize={11} fill="var(--text)">
              {lane.label.length > 26 ? `${lane.label.slice(0, 25)}…` : lane.label}
            </text>
            <text x={8} y={AXIS_HEIGHT + i * LANE_HEIGHT + 34} fontSize={10} fill="var(--muted)">
              {lane.root ? "earliest narrative" : lane.narrative ? "branch" : ""}
            </text>
          </g>
        ))}
        {model.sightings.map((s) => {
          if (!s.date_upper) return null;
          const lane = laneIndex[model.laneOf[s.id]] ?? model.lanes.length - 1;
          const cy = AXIS_HEIGHT + lane * LANE_HEIGHT + LANE_HEIGHT / 2;
          const upper = x(new Date(s.date_upper));
          const lower = s.date_lower ? x(new Date(s.date_lower)) : upper;
          const earliest = s.id === model.earliestId;
          const isSelected = s.id === selected;
          const divergence = Object.values(model.divergenceOf).includes(s.id);
          const colour = CONFIDENCE_COLOUR[s.date_confidence] ?? "var(--muted)";
          return (
            <g
              key={s.id}
              role="button"
              tabIndex={0}
              aria-label={`${s.domain}: ${formatInterval(s.date_lower, s.date_upper)}`}
              onClick={() => onSelect(s.id)}
              onKeyDown={(event) => event.key === "Enter" && onSelect(s.id)}
              className="cursor-pointer outline-none"
            >
              {lower < upper ? <rect x={lower} y={cy - 3} width={upper - lower} height={6} fill={colour} opacity={0.35} /> : null}
              <circle
                cx={upper}
                cy={cy}
                r={isSelected ? 7 : 5}
                fill={colour}
                stroke={earliest ? "var(--accent)" : isSelected ? "var(--text)" : "none"}
                strokeWidth={earliest ? 3 : 1.5}
              />
              {divergence ? (
                <text x={upper} y={cy - 10} textAnchor="middle" fontSize={9} fill="var(--muted)">
                  diverges
                </text>
              ) : null}
              {earliest ? (
                <text x={upper} y={cy + 18} textAnchor="middle" fontSize={9} fill="var(--accent)">
                  earliest found
                </text>
              ) : null}
            </g>
          );
        })}
      </svg>
    </div>
  );
}
