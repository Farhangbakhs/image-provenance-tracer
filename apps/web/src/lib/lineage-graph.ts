import { scaleUtc, type ScaleTime } from "d3-scale";

import type { RunAnalysisOut, SightingOut } from "./api/client";
import { timeExtent } from "./timeScale";
import type { WorkspaceModel } from "./workspace";

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

/** World units: the full time range spans at least this width; zoom reaches any day. */
export const WORLD_MIN_WIDTH = 1600;
export const LANE_GAP = 150;

export type LinkKind = "same" | "crop" | "mirror" | "resize" | "overlay" | "recompress" | "forward";

export interface GraphNode {
  id: string;
  sighting: SightingOut;
  /** Where time puts the node; the x force pulls it here. */
  timeX: number;
  /** Its variant's lane; the y force pulls it here, loosely. */
  laneY: number;
  variant: string;
  earliest: boolean;
  /** Set by the simulation. */
  x?: number;
  y?: number;
  fx?: number;
  fy?: number;
}

export interface GraphLink {
  source: string;
  target: string;
  kind: LinkKind;
  /** Shown along the link when zoomed in. */
  label: string;
}

export interface GraphLane {
  label: string;
  y: number;
  count: number;
  derivedFrom: string | null;
}

export interface DayGroup {
  day: string;
  ids: string[];
}

export interface LineageGraphData {
  nodes: GraphNode[];
  links: GraphLink[];
  lanes: GraphLane[];
  days: DayGroup[];
  scale: ScaleTime<number, number>;
  width: number;
}


/**
 * Where a copy sits on the axis: the earliest date the evidence allows, else the date it is
 * proven online. Many copies are proven only by ORIGIN's own fetch (today), so the lower bound
 * says far more about when a copy appeared; the full interval stays in the evidence.
 */
export function placedAt(s: SightingOut): string | null {
  return s.date_lower ?? s.date_upper ?? null;
}

function whenIso(s: SightingOut): string | null {
  return placedAt(s);
}

/**
 * The lineage as a graph on a time axis. Nodes are copies, placed in x by when they were proven
 * online and grouped in y by variant. Links: consecutive copies of the same variant (faint),
 * derived-from edges between variants (labelled with the edit) and Telegram forwards.
 */
export function buildLineageGraph(model: WorkspaceModel, analysis: RunAnalysisOut): LineageGraphData {
  const rows = lineageRows(model, analysis);
  const dated = model.sightings.filter((s) => whenIso(s));
  const width = Math.max(WORLD_MIN_WIDTH, dated.length * 70);
  const scale = scaleUtc().domain(timeExtent(model.sightings)).range([0, width]);
  const lanes: GraphLane[] = rows.map((row, i) => ({
    label: row.label,
    y: i * LANE_GAP,
    count: row.sightings.length,
    derivedFrom: row.derivedFrom,
  }));

  const nodes: GraphNode[] = [];
  const links: GraphLink[] = [];
  rows.forEach((row, i) => {
    const placed = row.sightings.filter((s) => whenIso(s));
    for (const s of placed) {
      nodes.push({
        id: s.id,
        sighting: s,
        timeX: scale(new Date(whenIso(s) as string)),
        laneY: i * LANE_GAP,
        variant: row.label,
        earliest: s.id === model.earliestId,
      });
    }
    for (let k = 1; k < placed.length; k += 1) {
      links.push({ source: placed[k - 1].id, target: placed[k].id, kind: "same", label: "" });
    }
  });

  const present = new Set(nodes.map((n) => n.id));
  const firstOf = Object.fromEntries(rows.map((r) => [r.id, r.sightings.find((s) => whenIso(s))?.id]));
  for (const e of analysis.edges) {
    const source = firstOf[e.parent_variant_id];
    const target = firstOf[e.child_variant_id];
    if (source && target && source !== target) {
      links.push({ source, target, kind: e.kind as LinkKind, label: EDGE_WORD[e.kind] ?? e.kind });
    }
  }
  for (const e of analysis.propagation) {
    if (present.has(e.from_sighting_id) && present.has(e.to_sighting_id)) {
      links.push({ source: e.from_sighting_id, target: e.to_sighting_id, kind: "forward", label: "forwarded" });
    }
  }

  const byDay = new Map<string, string[]>();
  for (const n of [...nodes].sort((a, b) => a.timeX - b.timeX)) {
    const day = (whenIso(n.sighting) as string).slice(0, 10);
    byDay.set(day, [...(byDay.get(day) ?? []), n.id]);
  }
  const days = groupDays([...byDay.entries()].map(([day, ids]) => ({ day, ids })));

  return { nodes, links, lanes, days, scale, width };
}

/** Day chips for jumping to a date; a busy run is grouped by month (then year) instead. */
export function groupDays(days: DayGroup[], most = 12): DayGroup[] {
  for (const width of [10, 7, 4]) {
    const grouped = new Map<string, string[]>();
    for (const d of days) grouped.set(d.day.slice(0, width), [...(grouped.get(d.day.slice(0, width)) ?? []), ...d.ids]);
    if (grouped.size <= most || width === 4) return [...grouped.entries()].map(([day, ids]) => ({ day, ids }));
  }
  return days;
}

/** Ids of a node and everything linked to it: what hovering lights up. */
export function neighbourhood(links: GraphLink[], id: string): Set<string> {
  const out = new Set([id]);
  for (const l of links) {
    const s = typeof l.source === "string" ? l.source : (l.source as { id: string }).id;
    const t = typeof l.target === "string" ? l.target : (l.target as { id: string }).id;
    if (s === id) out.add(t);
    if (t === id) out.add(s);
  }
  return out;
}
