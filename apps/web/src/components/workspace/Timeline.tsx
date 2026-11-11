"use client";

import { CONFIDENCE_COLOUR, type WorkspaceModel } from "@/lib/workspace";
import { formatInterval } from "@/lib/time";
import { useZoomableTime } from "@/lib/timeScale";

const LANE_HEIGHT = 60;
const LABEL_WIDTH = 210;
const AXIS_HEIGHT = 30;
const WIDTH = 1000;

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
  const { x, svg, onWheel, fit, ticks, format } = useZoomableTime(model.sightings, [LABEL_WIDTH + 12, WIDTH - 20], WIDTH);
  const height = AXIS_HEIGHT + model.lanes.length * LANE_HEIGHT;
  const laneIndex = Object.fromEntries(model.lanes.map((lane, i) => [lane.id, i]));
  // Only a branch has a point where the story changed; the first story has none.
  const branchStarts = new Set(model.lanes.filter((l) => l.narrative && !l.root).map((l) => model.divergenceOf[l.id]));

  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-2 px-3 py-2 text-[13px] text-muted">
        <span>
          Rows are the stories told about the picture. Each dot is a copy at the date it is proven online; the band
          behind it reaches back to the earliest it could have appeared. Scroll to zoom.
        </span>
        <button type="button" onClick={fit} className="border border-line px-2 py-0.5 text-[12px] hover:border-intent hover:text-text">
          Fit all
        </button>
      </div>
      <div className="overflow-x-auto">
      <svg
        ref={svg}
        viewBox={`0 0 ${WIDTH} ${height}`}
        className="block w-full min-w-[1000px] select-none"
        role="img"
        aria-label="Timeline of sightings by narrative"
        onWheel={onWheel}
      >
        {ticks.map((t) => (
          <g key={t.getTime()}>
            <line x1={x(t)} x2={x(t)} y1={AXIS_HEIGHT - 4} y2={height} stroke="var(--line)" strokeDasharray="2 3" />
            <text x={x(t)} y={18} textAnchor="middle" className="mono" fontSize={11} fill="var(--muted)">
              {format(t)}
            </text>
          </g>
        ))}
        {model.lanes.map((lane, i) => (
          <g key={lane.id}>
            <line x1={0} x2={WIDTH} y1={AXIS_HEIGHT + i * LANE_HEIGHT} y2={AXIS_HEIGHT + i * LANE_HEIGHT} stroke="var(--line)" />
            <title>{lane.label}</title>
            <text x={10} y={AXIS_HEIGHT + i * LANE_HEIGHT + 24} fontSize={13} fontWeight={600} fill="var(--text)">
              {lane.label.length > 28 ? `${lane.label.slice(0, 27)}…` : lane.label}
            </text>
            <text x={10} y={AXIS_HEIGHT + i * LANE_HEIGHT + 42} fontSize={11} fill="var(--faint)">
              {lane.root ? "first story found" : lane.narrative ? "branch: a contradicting story" : "pages that made no claim"}
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
          const divergence = branchStarts.has(s.id);
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
                stroke={earliest ? "var(--accent)" : isSelected ? "var(--intent)" : "var(--bg)"}
                strokeWidth={earliest ? 3 : 1.5}
              />
              {divergence ? (
                <text x={upper} y={cy - 12} textAnchor="middle" fontSize={11} fill="var(--text)">
                  story changes here
                </text>
              ) : null}
              {earliest ? (
                <text x={upper} y={cy + 21} textAnchor="middle" fontSize={11} fontWeight={600} fill="var(--accent)">
                  earliest found
                </text>
              ) : null}
            </g>
          );
        })}
      </svg>
      </div>
    </div>
  );
}
