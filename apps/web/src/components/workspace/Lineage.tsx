"use client";

import { API_URL, type RunAnalysisOut, type SightingOut } from "@/lib/api/client";
import { formatInterval } from "@/lib/time";
import { useZoomableTime } from "@/lib/timeScale";
import { CONFIDENCE_COLOUR, type WorkspaceModel } from "@/lib/workspace";

const WIDTH = 1000;
const LABEL_WIDTH = 210;
const AXIS_HEIGHT = 30;
const ROW_HEIGHT = 84;
const THUMB = { w: 52, h: 40 };

const EDGE_WORD: Record<string, string> = {
  crop: "cropped",
  mirror: "mirrored",
  resize: "resized",
  overlay: "captioned",
  recompress: "recompressed",
};

export interface LineageRow {
  id: string;
  label: string;
  sightings: SightingOut[];
  /** The variant's earliest-dated sighting: where its arrows start and end. */
  first: SightingOut | null;
  /** "cropped from V1" when this variant was derived from another. */
  derivedFrom: string | null;
}

function short(domain: string): string {
  const bare = domain.replace(/^www\./, "");
  return bare.length > 20 ? `${bare.slice(0, 19)}…` : bare;
}

function when(s: SightingOut): number {
  return new Date(s.date_upper ?? s.date_lower ?? 8.64e15).getTime();
}

/** Variants as rows ordered by their earliest copy, each with what it was derived from. */
export function lineageRows(model: WorkspaceModel, analysis: RunAnalysisOut): LineageRow[] {
  const byId = Object.fromEntries(model.sightings.map((s) => [s.id, s]));
  const labelOf = Object.fromEntries(analysis.variants.map((v) => [v.id, v.label]));
  const parentEdges: Record<string, string[]> = {};
  for (const e of analysis.edges) {
    (parentEdges[e.child_variant_id] ??= []).push(`${EDGE_WORD[e.kind] ?? e.kind} from ${labelOf[e.parent_variant_id] ?? "?"}`);
  }
  const rows = analysis.variants.map((v) => {
    const sightings = v.sighting_ids.map((id) => byId[id]).filter((s): s is SightingOut => Boolean(s));
    sightings.sort((a, b) => when(a) - when(b));
    return {
      id: v.id,
      label: v.label,
      sightings,
      first: sightings[0] ?? null,
      derivedFrom: parentEdges[v.id]?.join("; ") ?? null,
    };
  });
  rows.sort((a, b) => (a.first ? when(a.first) : Infinity) - (b.first ? when(b.first) : Infinity));
  return rows;
}

/**
 * The lineage of the picture on one horizontal time axis. Each row is a variant (copies that
 * look the same); each dot is a copy at the date it is proven online, with a band back to the
 * earliest it could have appeared. Solid arrows run from a variant to an edit made from it;
 * dashed arrows are Telegram forwards. Scroll to zoom.
 */
export function Lineage({
  model,
  analysis,
  selected,
  onSelect,
}: {
  model: WorkspaceModel;
  analysis: RunAnalysisOut;
  selected: string | null;
  onSelect: (id: string) => void;
}) {
  const rows = lineageRows(model, analysis);
  const { x, svg, onWheel, fit, ticks, format } = useZoomableTime(model.sightings, [LABEL_WIDTH + 12, WIDTH - 20], WIDTH);
  const height = AXIS_HEIGHT + Math.max(rows.length, 1) * ROW_HEIGHT + 8;
  const rowOf: Record<string, number> = {};
  rows.forEach((row, i) => row.sightings.forEach((s) => (rowOf[s.id] = i)));
  const point = (s: SightingOut) => ({
    x: x(new Date(s.date_upper ?? s.date_lower ?? x.domain()[1])),
    y: AXIS_HEIGHT + (rowOf[s.id] ?? 0) * ROW_HEIGHT + ROW_HEIGHT / 2,
  });
  const byId = Object.fromEntries(model.sightings.map((s) => [s.id, s]));
  const rowById = Object.fromEntries(rows.map((r) => [r.id, r]));

  // Arrows stop just short of the dot they point at, so the arrowhead stays visible.
  const curve = (a: { x: number; y: number }, b: { x: number; y: number }) => {
    const bend = Math.max(24, Math.abs(b.x - a.x) / 2);
    const end = b.x - 9;
    return `M ${a.x + 6} ${a.y} C ${a.x + bend} ${a.y}, ${end - bend} ${b.y}, ${end} ${b.y}`;
  };

  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-2 px-3 py-2 text-[13px] text-muted">
        <span>
          Rows are variants, ordered by their earliest copy. Arrows run from a picture to the edit made from it. Scroll
          over the chart to zoom.
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
          aria-label="Lineage: variants of the picture over time"
          onWheel={onWheel}
        >
          <defs>
            <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
              <path d="M 0 0 L 10 5 L 0 10 z" fill="var(--muted)" />
            </marker>
            <marker id="arrow-forward" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
              <path d="M 0 0 L 10 5 L 0 10 z" fill="var(--intent)" />
            </marker>
            <clipPath id="plot">
              <rect x={LABEL_WIDTH} y={0} width={WIDTH - LABEL_WIDTH} height={height} />
            </clipPath>
          </defs>

          {/* Axis and gridlines */}
          {ticks.map((t) => (
            <g key={t.getTime()}>
              <line x1={x(t)} x2={x(t)} y1={AXIS_HEIGHT - 4} y2={height} stroke="var(--line)" strokeDasharray="2 3" />
              <text x={x(t)} y={18} textAnchor="middle" className="mono" fontSize={11} fill="var(--muted)">
                {format(t)}
              </text>
            </g>
          ))}

          {/* Rows: thumbnail, label, what it was derived from */}
          {rows.map((row, i) => {
            const top = AXIS_HEIGHT + i * ROW_HEIGHT;
            const rep = row.first;
            return (
              <g key={row.id}>
                <rect x={0} y={top} width={WIDTH} height={ROW_HEIGHT} fill={i % 2 ? "var(--surface-1)" : "transparent"} opacity={0.6} />
                <line x1={0} x2={WIDTH} y1={top} y2={top} stroke="var(--line)" />
                {rep ? (
                  <image
                    href={`${API_URL}/sightings/${rep.id}/image`}
                    x={8}
                    y={top + (ROW_HEIGHT - THUMB.h) / 2}
                    width={THUMB.w}
                    height={THUMB.h}
                    preserveAspectRatio="xMidYMid slice"
                  />
                ) : null}
                <text x={THUMB.w + 18} y={top + 24} fontSize={13} fontWeight={600} fill="var(--text)" className="mono">
                  {row.label}
                </text>
                <text x={THUMB.w + 18 + 34} y={top + 24} fontSize={12} fill="var(--muted)">
                  {row.sightings.length} cop{row.sightings.length === 1 ? "y" : "ies"}
                </text>
                <text x={THUMB.w + 18} y={top + 42} fontSize={11} fill="var(--faint)">
                  {row.derivedFrom ? (row.derivedFrom.length > 24 ? `${row.derivedFrom.slice(0, 23)}…` : row.derivedFrom) : "earliest form found"}
                </text>
              </g>
            );
          })}
          <line x1={LABEL_WIDTH} x2={LABEL_WIDTH} y1={AXIS_HEIGHT} y2={height} stroke="var(--line)" />

          <g clipPath="url(#plot)">
            {/* Derived-from arrows between variants */}
            {analysis.edges.map((e) => {
              const parent = rowById[e.parent_variant_id]?.first;
              const child = rowById[e.child_variant_id]?.first;
              if (!parent || !child) return null;
              const a = point(parent);
              const b = point(child);
              return (
                <g key={`${e.parent_variant_id}-${e.child_variant_id}-${e.kind}`}>
                  <path d={curve(a, b)} fill="none" stroke="var(--muted)" strokeWidth={1.25} markerEnd="url(#arrow)" opacity={0.85} />
                  <text x={(a.x + b.x) / 2} y={(a.y + b.y) / 2 - 6} textAnchor="middle" fontSize={11} fill="var(--muted)">
                    {EDGE_WORD[e.kind] ?? e.kind}
                  </text>
                </g>
              );
            })}

            {/* Telegram forwards between copies */}
            {analysis.propagation.map((e) => {
              const from = byId[e.from_sighting_id];
              const to = byId[e.to_sighting_id];
              if (!from || !to) return null;
              const a = point(from);
              const b = point(to);
              const sameRow = Math.abs(a.y - b.y) < 1;
              const d = sameRow
                ? `M ${a.x + 2} ${a.y - 7} Q ${(a.x + b.x) / 2} ${a.y - 34} ${b.x - 3} ${b.y - 9}`
                : curve(a, b);
              return (
                <g key={`${e.from_sighting_id}-${e.to_sighting_id}`}>
                  <path d={d} fill="none" stroke="var(--intent)" strokeWidth={1.5} strokeDasharray="5 4" markerEnd="url(#arrow-forward)" />
                  <text x={(a.x + b.x) / 2} y={(sameRow ? a.y - 24 : (a.y + b.y) / 2 - 6)} textAnchor="middle" fontSize={11} fill="var(--intent)">
                    forwarded
                  </text>
                </g>
              );
            })}

            {/* Copies */}
            {rows.flatMap((row) =>
              row.sightings.map((s) => {
                if (!s.date_upper && !s.date_lower) return null;
                const p = point(s);
                const lower = s.date_lower ? x(new Date(s.date_lower)) : p.x;
                const earliest = s.id === model.earliestId;
                const isSelected = s.id === selected;
                // Name each copy when the row is sparse enough to read.
                const labelled = row.sightings.length <= 4;
                const colour = CONFIDENCE_COLOUR[s.date_confidence] ?? "var(--muted)";
                return (
                  <g
                    key={s.id}
                    role="button"
                    tabIndex={0}
                    aria-label={`${s.domain}, variant ${row.label}: ${formatInterval(s.date_lower, s.date_upper)}`}
                    onClick={() => onSelect(s.id)}
                    onKeyDown={(event) => event.key === "Enter" && onSelect(s.id)}
                    className="cursor-pointer outline-none"
                  >
                    <title>{`${s.domain} · ${formatInterval(s.date_lower, s.date_upper)} · ${s.date_confidence} confidence`}</title>
                    {lower < p.x ? <rect x={lower} y={p.y - 3} width={p.x - lower} height={6} fill={colour} opacity={0.3} /> : null}
                    <circle
                      cx={p.x}
                      cy={p.y}
                      r={isSelected ? 7 : 5.5}
                      fill={colour}
                      stroke={earliest ? "var(--accent)" : isSelected ? "var(--intent)" : "var(--bg)"}
                      strokeWidth={earliest || isSelected ? 3 : 1.5}
                    />
                    {earliest || labelled ? (
                      <text
                        x={p.x}
                        y={p.y + 21}
                        textAnchor="middle"
                        fontSize={11}
                        fontWeight={earliest ? 600 : 400}
                        fill={earliest ? "var(--accent)" : "var(--faint)"}
                      >
                        {earliest ? "earliest found" : short(s.domain)}
                      </text>
                    ) : null}
                  </g>
                );
              }),
            )}
          </g>
        </svg>
      </div>
      <ul className="flex flex-wrap gap-x-5 gap-y-1 border-t border-line px-3 py-2 text-[12px] text-muted" aria-label="Legend">
        <li className="flex items-center gap-1.5">
          <span className="inline-block size-2.5 rounded-full border-2 border-accent" /> earliest found
        </li>
        <li className="flex items-center gap-1.5">
          <span className="inline-block size-2.5 rounded-full bg-conf-high" /> high
          <span className="inline-block size-2.5 rounded-full bg-conf-medium" /> medium
          <span className="inline-block size-2.5 rounded-full bg-conf-low" /> low dating confidence
        </li>
        <li className="flex items-center gap-1.5">
          <span className="inline-block h-1.5 w-6 bg-muted opacity-40" /> could have appeared from here
        </li>
        <li className="flex items-center gap-1.5">
          <span className="inline-block w-6 border-t border-muted" /> edit made from
        </li>
        <li className="flex items-center gap-1.5">
          <span className="inline-block w-6 border-t-2 border-dashed border-intent" /> Telegram forward
        </li>
      </ul>
    </div>
  );
}
