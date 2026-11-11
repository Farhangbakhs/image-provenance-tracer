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

export type LinkKind = "crop" | "mirror" | "resize" | "overlay" | "recompress" | "forward";

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
export type GroupBy = "variant" | "story";

/**
 * The investigation as a graph on a time axis. Nodes are copies, placed in x at the earliest
 * date their evidence allows and banded in y by variant (how the picture looks) or by story
 * (what its page says). Links are derived-from edges between variants, labelled with the edit,
 * and Telegram forwards.
 */
export function buildLineageGraph(
  model: WorkspaceModel,
  analysis: RunAnalysisOut,
  groupBy: GroupBy = "variant",
): LineageGraphData {
  const rows = lineageRows(model, analysis);
  const dated = model.sightings.filter((s) => whenIso(s));
  const width = Math.max(WORLD_MIN_WIDTH, dated.length * 70);
  // The axis spans where copies are placed, not every bound: most proven bounds are "today".
  const placedOnly = dated.map((s) => ({ ...s, date_lower: whenIso(s), date_upper: whenIso(s) }));
  const scale = scaleUtc().domain(timeExtent(placedOnly)).range([0, width]);

  const bandOf: Record<string, number> = {};
  const lanes: GraphLane[] = [];
  if (groupBy === "variant") {
    rows.forEach((row, i) => {
      lanes.push({ label: row.label, y: i * LANE_GAP, count: row.sightings.length, derivedFrom: row.derivedFrom });
      for (const s of row.sightings) bandOf[s.id] = i;
    });
  } else {
    model.lanes.forEach((lane, i) => {
      const count = model.sightings.filter((s) => model.laneOf[s.id] === lane.id).length;
      lanes.push({
        label: lane.label,
        y: i * LANE_GAP,
        count,
        derivedFrom: lane.root ? "first story found" : lane.narrative ? "a contradicting story" : null,
      });
      for (const s of model.sightings) if (model.laneOf[s.id] === lane.id) bandOf[s.id] = i;
    });
  }
  const variantOf = Object.fromEntries(rows.flatMap((r) => r.sightings.map((s) => [s.id, r.label])));

  const nodes: GraphNode[] = dated.map((s) => ({
    id: s.id,
    sighting: s,
    timeX: scale(new Date(whenIso(s) as string)),
    laneY: (bandOf[s.id] ?? lanes.length) * LANE_GAP,
    variant: variantOf[s.id] ?? "",
    earliest: s.id === model.earliestId,
  }));

  const links: GraphLink[] = [];
  const present = new Set(nodes.map((n) => n.id));
  const firstOf = Object.fromEntries(rows.map((r) => [r.id, r.sightings.find((s) => whenIso(s))?.id]));
  // Several edits between the same two variants are one link: "cropped, resized".
  const merged = new Map<string, GraphLink>();
  for (const e of analysis.edges) {
    const source = firstOf[e.parent_variant_id];
    const target = firstOf[e.child_variant_id];
    if (!source || !target || source === target) continue;
    const key = `${source}>${target}`;
    const word = EDGE_WORD[e.kind] ?? e.kind;
    const existing = merged.get(key);
    if (existing) existing.label = `${existing.label}, ${word}`;
    else merged.set(key, { source, target, kind: e.kind as LinkKind, label: word });
  }
  links.push(...merged.values());
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
