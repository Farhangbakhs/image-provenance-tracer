"use client";

import { forceCollide, forceManyBody, forceX, forceY } from "d3-force";
import dynamic from "next/dynamic";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type ForceGraphComponent from "react-force-graph-2d";
import type { ForceGraphMethods, LinkObject, NodeObject } from "react-force-graph-2d";

import { API_URL, type RunAnalysisOut } from "@/lib/api/client";
import { explainDate, explainMatch } from "@/lib/explain";
import {
  buildLineageGraph,
  neighbourhood,
  placedAt,
  type GraphLink,
  type GraphNode,
  type GroupBy,
} from "@/lib/lineage-graph";
import { formatInterval } from "@/lib/time";
import type { WorkspaceModel } from "@/lib/workspace";

// The graph draws on a canvas in the browser; it has nothing to render on the server.
const ForceGraph2D = dynamic(() => import("react-force-graph-2d"), { ssr: false }) as unknown as typeof ForceGraphComponent;

type Node = NodeObject<GraphNode>;
type Link = LinkObject<GraphNode, GraphLink>;

const NODE = 40; // thumbnail side, in world units
const MIN_SCREEN = 24; // and never smaller than this many pixels on screen
const HEIGHT = 600;
const GUTTER = 168; // screen pixels kept for band labels on the left

/** Colours from the design tokens, read once from CSS so the canvas matches the console. */
function palette() {
  const css = getComputedStyle(document.documentElement);
  const v = (name: string, fallback: string) => css.getPropertyValue(name).trim() || fallback;
  return {
    bg: v("--bg", "#111418"),
    band: v("--surface-1", "#1c2127"),
    line: v("--line", "#383e47"),
    surface: v("--surface-2", "#252a31"),
    text: v("--text", "#f6f7f9"),
    muted: v("--muted", "#abb3bf"),
    faint: v("--faint", "#8f99a8"),
    accent: v("--accent", "#22bed2"),
    conf: {
      high: v("--conf-high", "#f6f7f9"),
      medium: v("--conf-medium", "#abb3bf"),
      low: v("--conf-low", "#6b7380"),
      unknown: v("--conf-low", "#6b7380"),
    } as Record<string, string>,
  };
}

function endId(end: Link["source"]): string {
  return typeof end === "object" && end !== null ? String((end as Node).id) : String(end);
}

/**
 * The investigation as one living graph, in the manner of Obsidian: every copy is a node showing
 * its image, held at its date on a horizontal time axis and loosely to its band (its variant,
 * or the story its page tells), with springy links for edits and forwards.
 *
 * The page keeps scrolling normally: zoom with Ctrl/⌘ + scroll, a pinch, the buttons or the
 * date chips. In full screen, plain scrolling zooms.
 */
export function InvestigationGraph({
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
  const [groupBy, setGroupBy] = useState<GroupBy>("variant");
  const data = useMemo(() => buildLineageGraph(model, analysis, groupBy), [model, analysis, groupBy]);
  const graph = useMemo(() => ({ nodes: data.nodes.map((n) => ({ ...n })), links: data.links.map((l) => ({ ...l })) }), [data]);
  const fg = useRef<ForceGraphMethods<Node, Link> | undefined>(undefined);
  const box = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ width: 900, height: HEIGHT });
  const [full, setFull] = useState(false);
  const [hover, setHover] = useState<string | null>(null);
  const [scrollHint, setScrollHint] = useState(false);
  // Rendered only in the browser (it needs the run's data), so the tokens can be read up front.
  const [colours] = useState<ReturnType<typeof palette> | null>(() => (typeof document === "undefined" ? null : palette()));
  const images = useRef(new Map<string, HTMLImageElement>());
  const lit = useMemo(() => (hover ? neighbourhood(data.links, hover) : null), [hover, data.links]);

  // Thumbnails, loaded once per copy.
  useEffect(() => {
    for (const n of data.nodes) {
      if (images.current.has(n.id)) continue;
      const img = new Image();
      img.src = `${API_URL}/sightings/${n.id}/image`;
      images.current.set(n.id, img);
    }
  }, [data.nodes]);

  // Fill the container, in and out of full screen; let the page scroll unless zoom is asked for.
  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const observer = new ResizeObserver(([entry]) =>
      setSize({ width: Math.floor(entry.contentRect.width), height: Math.floor(entry.contentRect.height) }),
    );
    observer.observe(el);
    const onFull = () => setFull(document.fullscreenElement === el);
    let hintTimer = 0;
    const onWheel = (event: WheelEvent) => {
      if (document.fullscreenElement === el || event.ctrlKey || event.metaKey) return;
      event.stopPropagation(); // the graph never sees it, so the page scrolls
      setScrollHint(true);
      window.clearTimeout(hintTimer);
      hintTimer = window.setTimeout(() => setScrollHint(false), 1200);
    };
    el.addEventListener("wheel", onWheel, { capture: true });
    document.addEventListener("fullscreenchange", onFull);
    return () => {
      observer.disconnect();
      el.removeEventListener("wheel", onWheel, { capture: true });
      document.removeEventListener("fullscreenchange", onFull);
      window.clearTimeout(hintTimer);
    };
  }, []);

  // Forces: time holds x firmly, the band holds y; charge, collision and links do the rest.
  const configure = useCallback(() => {
    const g = fg.current;
    if (!g) return;
    g.d3Force("x", forceX<Node>((n) => n.timeX).strength(0.85));
    g.d3Force("y", forceY<Node>((n) => n.laneY).strength(0.18));
    g.d3Force("charge", forceManyBody<Node>().strength(-90).distanceMax(320));
    g.d3Force("collide", forceCollide<Node>(NODE * 0.75));
    g.d3Force("center", null);
    const link = g.d3Force("link");
    link?.distance?.(90);
    link?.strength?.(0.04);
    g.d3ReheatSimulation();
  }, []);

  // The graph component loads lazily, so forces are set on its first frame and whenever the data
  // changes; the first settle then fits everything in view.
  const configured = useRef<object | null>(null);
  const fitted = useRef(false);
  useEffect(() => {
    fitted.current = false;
  }, [graph]);

  /**
   * Fit all copies, or one day's, into the part of the canvas right of the label gutter. A lone
   * copy is centred at a readable zoom rather than filling the screen.
   */
  const fit = (ids?: string[], duration = 600) => {
    const g = fg.current;
    if (!g) return;
    const set = ids ? new Set(ids) : null;
    const nodes = graph.nodes.filter((n) => n.x !== undefined && n.y !== undefined && (!set || set.has(n.id)));
    if (nodes.length === 0) return;
    const pad = 70;
    const xs = nodes.map((n) => n.x as number);
    const ys = nodes.map((n) => n.y as number);
    const [x0, x1, y0, y1] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
    const room = { w: Math.max(200, size.width - GUTTER - 2 * pad), h: Math.max(200, size.height - 2 * pad) };
    const fitted = Math.min(room.w / Math.max(x1 - x0, 1), room.h / Math.max(y1 - y0, 1));
    const k = Math.min(nodes.length === 1 ? 3 : 4, Math.max(0.05, fitted));
    // Centre in the free area: shift left by half the gutter, in world units.
    g.zoom(k, duration);
    g.centerAt((x0 + x1) / 2 - GUTTER / 2 / k, (y0 + y1) / 2, duration);
  };
  const zoomBy = (factor: number) => {
    const g = fg.current;
    if (g) g.zoom((g.zoom() ?? 1) * factor, 250);
  };

  const toggleFull = () => {
    const el = box.current;
    if (!el) return;
    if (document.fullscreenElement) void document.exitFullscreen();
    else void el.requestFullscreen();
  };

  const drawNode = (node: Node, ctx: CanvasRenderingContext2D, scale: number) => {
    if (!colours || node.x === undefined || node.y === undefined) return;
    const id = String(node.id);
    const dim = lit !== null && !lit.has(id);
    const s = node.sighting;
    const side = Math.max(NODE, MIN_SCREEN / scale);
    const half = side / 2;
    ctx.globalAlpha = dim ? 0.15 : 1;
    ctx.fillStyle = colours.surface;
    ctx.fillRect(node.x - half, node.y - half, side, side);
    const img = images.current.get(id);
    if (img?.complete && img.naturalWidth > 0) {
      const crop = Math.min(img.naturalWidth, img.naturalHeight);
      ctx.drawImage(
        img,
        (img.naturalWidth - crop) / 2,
        (img.naturalHeight - crop) / 2,
        crop,
        crop,
        node.x - half,
        node.y - half,
        side,
        side,
      );
    }
    // Frame: a step of grey for dating confidence. The accent marks the earliest found; white,
    // the copy you are looking at.
    ctx.lineWidth = 1.5 / scale + 0.5;
    ctx.strokeStyle = colours.conf[s.date_confidence] ?? colours.faint;
    ctx.strokeRect(node.x - half, node.y - half, side, side);
    const ring = 4 / scale + 1;
    if (node.earliest) {
      ctx.lineWidth = 3 / scale + 1;
      ctx.strokeStyle = colours.accent;
      ctx.strokeRect(node.x - half - ring, node.y - half - ring, side + 2 * ring, side + 2 * ring);
    }
    if (id === selected || id === hover) {
      ctx.lineWidth = 2 / scale + 0.5;
      ctx.strokeStyle = colours.text;
      const r = ring * (node.earliest ? 2 : 1);
      ctx.strokeRect(node.x - half - r, node.y - half - r, side + 2 * r, side + 2 * r);
    }
    // Labels: always for a small graph, fading in with zoom for a big one.
    const fade = data.nodes.length <= 15 ? 1 : Math.min(1, Math.max(0, (scale - 0.9) / 0.8));
    const show = Math.max(fade, id === hover || node.earliest ? 1 : 0);
    if (show > 0 && !dim) {
      const font = Math.max(11 / scale, 3);
      ctx.globalAlpha = show;
      ctx.font = `${node.earliest ? 600 : 400} ${font}px Inter, system-ui, sans-serif`;
      ctx.textAlign = "center";
      ctx.textBaseline = "top";
      ctx.fillStyle = node.earliest ? colours.accent : colours.muted;
      const name = s.domain.replace(/^www\./, "");
      const top = node.y + half + ring + 3 / scale;
      ctx.fillText(node.earliest ? `Earliest found · ${name}` : name, node.x, top);
      const at = placedAt(s);
      if (fade > 0.5 && at) {
        ctx.fillStyle = colours.faint;
        ctx.font = `${Math.max(10 / scale, 2.6)}px "JetBrains Mono", ui-monospace, monospace`;
        ctx.fillText(at.slice(0, 10), node.x, top + font * 1.3);
      }
    }
    ctx.globalAlpha = 1;
  };

  const drawLinkLabel = (link: Link, ctx: CanvasRenderingContext2D, scale: number) => {
    if (!colours || !link.label || scale < 0.6) return;
    const a = link.source as Node;
    const b = link.target as Node;
    if (a.x === undefined || b.x === undefined || a.y === undefined || b.y === undefined) return;
    if (lit !== null && !(lit.has(String(a.id)) && lit.has(String(b.id)))) return;
    ctx.font = `${Math.max(11 / scale, 3)}px Inter, system-ui, sans-serif`;
    ctx.textAlign = "center";
    ctx.textBaseline = "bottom";
    ctx.fillStyle = colours.muted;
    ctx.fillText(link.label, (a.x + b.x) / 2, (a.y + b.y) / 2 - 4 / scale);
  };

  // Bands and the time axis, redrawn for whatever part of the world is on screen.
  const drawFrame = (ctx: CanvasRenderingContext2D, scale: number) => {
    const g = fg.current;
    if (!colours || !g) return;
    if (configured.current !== graph) {
      configured.current = graph;
      configure();
    }
    const topLeft = g.screen2GraphCoords(0, 0);
    const bottomRight = g.screen2GraphCoords(size.width, size.height);
    const left = topLeft.x;
    const width = bottomRight.x - topLeft.x;
    ctx.save();
    // Bands: alternate stripes, so a node's group reads at a glance.
    data.lanes.forEach((lane, i) => {
      if (i % 2 === 0) return;
      ctx.fillStyle = colours.band;
      ctx.fillRect(left, lane.y - 75, width, 150);
    });
    // Time axis: dashed gridlines with dates along the top.
    const visible = data.scale.copy().domain([data.scale.invert(left + GUTTER / scale), data.scale.invert(bottomRight.x)]);
    const count = Math.max(2, Math.floor((size.width - GUTTER) / 150));
    ctx.lineWidth = 1 / scale;
    ctx.setLineDash([3 / scale, 5 / scale]);
    ctx.strokeStyle = colours.line;
    ctx.fillStyle = colours.faint;
    ctx.font = `${11 / scale}px "JetBrains Mono", ui-monospace, monospace`;
    ctx.textAlign = "center";
    ctx.textBaseline = "top";
    const format = visible.tickFormat(count);
    for (const t of visible.ticks(count)) {
      const x = data.scale(t);
      ctx.beginPath();
      ctx.moveTo(x, topLeft.y + 24 / scale);
      ctx.lineTo(x, bottomRight.y);
      ctx.stroke();
      ctx.fillText(format(t), x, topLeft.y + 8 / scale);
    }
    ctx.setLineDash([]);
    // Band labels in a gutter on the left, always readable.
    ctx.fillStyle = colours.bg;
    ctx.globalAlpha = 0.88;
    ctx.fillRect(left, topLeft.y, GUTTER / scale, bottomRight.y - topLeft.y);
    ctx.globalAlpha = 1;
    ctx.textAlign = "left";
    ctx.textBaseline = "middle";
    const clip = (text: string, max: number) => (text.length > max ? `${text.slice(0, max - 1)}…` : text);
    for (const lane of data.lanes) {
      ctx.fillStyle = colours.text;
      ctx.font = `600 ${12 / scale}px Inter, system-ui, sans-serif`;
      ctx.fillText(clip(lane.label, 22), left + 12 / scale, lane.y - 9 / scale);
      ctx.fillStyle = colours.faint;
      ctx.font = `${11 / scale}px Inter, system-ui, sans-serif`;
      ctx.fillText(
        clip(`${lane.count} cop${lane.count === 1 ? "y" : "ies"}${lane.derivedFrom ? ` · ${lane.derivedFrom}` : ""}`, 26),
        left + 12 / scale,
        lane.y + 9 / scale,
      );
    }
    ctx.restore();
  };

  const linkColour = (l: Link) => {
    if (!colours) return "#555";
    const dim = lit !== null && !(lit.has(endId(l.source)) && lit.has(endId(l.target)));
    return dim ? `${colours.line}` : colours.muted;
  };

  const current = model.sightings.find((s) => s.id === selected) ?? null;
  const button = "border border-line px-2 py-1 text-[12px] text-muted hover:border-accent hover:text-text";

  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-3 py-2">
        <div role="radiogroup" aria-label="Group copies by" className="flex items-center gap-2 text-[12px]">
          <span className="label">Group by</span>
          {(
            [
              ["variant", "How it looks"],
              ["story", "What it claims"],
            ] as const
          ).map(([value, label]) => (
            <button
              key={value}
              type="button"
              role="radio"
              aria-checked={groupBy === value}
              onClick={() => setGroupBy(value)}
              className={`border px-2 py-1 ${groupBy === value ? "border-accent bg-accent-soft text-text" : "border-line text-muted hover:text-text"}`}
            >
              {label}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-1.5">
          <button type="button" onClick={() => zoomBy(1 / 1.6)} className={button} aria-label="Zoom out">
            −
          </button>
          <button type="button" onClick={() => zoomBy(1.6)} className={button} aria-label="Zoom in">
            +
          </button>
          <button type="button" onClick={() => fit()} className={button}>
            Fit
          </button>
          <button type="button" onClick={toggleFull} className={button}>
            {full ? "Exit full screen" : "Full screen"}
          </button>
        </div>
      </div>

      <div
        ref={box}
        className="relative w-full overflow-hidden bg-bg"
        style={{ height: full ? "100vh" : HEIGHT }}
        aria-label="Graph of the copies over time"
        role="img"
      >
        {colours ? (
          <ForceGraph2D<GraphNode, GraphLink>
            ref={fg}
            graphData={graph}
            width={size.width}
            height={size.height}
            backgroundColor={colours.bg}
            nodeId="id"
            nodeCanvasObject={drawNode}
            nodePointerAreaPaint={(node, colour, ctx) => {
              if (node.x === undefined || node.y === undefined) return;
              ctx.fillStyle = colour;
              ctx.fillRect(node.x - NODE / 2 - 4, node.y - NODE / 2 - 4, NODE + 8, NODE + 8);
            }}
            nodeLabel={(n) => `${n.sighting.domain} · ${formatInterval(n.sighting.date_lower, n.sighting.date_upper)}`}
            linkColor={linkColour}
            linkWidth={1.4}
            linkLineDash={(l) => (l.kind === "forward" ? [5, 4] : null)}
            linkDirectionalArrowLength={6}
            linkDirectionalArrowRelPos={0.92}
            linkDirectionalArrowColor={linkColour}
            linkCurvature={(l) => (l.kind === "forward" ? 0.25 : 0)}
            linkCanvasObjectMode={() => "after"}
            linkCanvasObject={drawLinkLabel}
            onRenderFramePre={drawFrame}
            onNodeHover={(n) => setHover(n ? String(n.id) : null)}
            onNodeClick={(n) => onSelect(String(n.id))}
            onNodeDragEnd={(n) => {
              // Released nodes spring back into the layout, as in Obsidian.
              n.fx = undefined;
              n.fy = undefined;
            }}
            onEngineStop={() => {
              if (!fitted.current) {
                fitted.current = true;
                fit(undefined, 400);
              }
            }}
            cooldownTicks={240}
            d3VelocityDecay={0.32}
            minZoom={0.05}
            maxZoom={40}
            autoPauseRedraw={false}
          />
        ) : null}

        {scrollHint ? (
          <p className="pointer-events-none absolute inset-x-0 top-1/2 mx-auto w-fit -translate-y-1/2 border border-line bg-surface-2 px-3 py-1.5 text-[13px]">
            Hold Ctrl (⌘ on Mac) and scroll to zoom, or use full screen
          </p>
        ) : null}

        {full && current ? (
          <aside className="absolute right-3 top-3 w-80 border border-line bg-surface-1 p-3 text-[13px]" aria-label="Selected copy">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={`${API_URL}${current.image_url_local}`} alt={`Copy on ${current.domain}`} className="mb-2 max-h-48 w-full border border-line object-contain" />
            <p className="font-semibold">{current.domain}</p>
            <p className="mt-1 text-muted">{explainMatch(current)}</p>
            <p className="mt-1 text-muted">{explainDate(current)}</p>
            <button type="button" onClick={() => void document.exitFullscreen()} className={`mt-2 ${button}`}>
              Open full evidence
            </button>
          </aside>
        ) : null}
      </div>

      <div className="flex flex-col gap-2 border-t border-line px-3 py-2 text-[12px] text-muted">
        <ul className="flex flex-wrap gap-x-5 gap-y-1" aria-label="Legend">
          <li className="flex items-center gap-1.5">
            <span className="inline-block size-3 border-2 border-accent" /> earliest found
          </li>
          <li className="flex items-center gap-1.5">
            frame: <span className="inline-block size-3 border border-conf-high" /> high
            <span className="inline-block size-3 border border-conf-medium" /> medium
            <span className="inline-block size-3 border border-conf-low" /> low dating confidence
          </li>
          <li className="flex items-center gap-1.5">
            <span className="inline-block w-5 border-t border-muted" /> edit made from
          </li>
          <li className="flex items-center gap-1.5">
            <span className="inline-block w-5 border-t border-dashed border-muted" /> Telegram forward
          </li>
          <li className="text-faint">x: earliest date the evidence allows</li>
        </ul>
        <div className="flex flex-wrap items-center gap-1.5" aria-label="Zoom to a date">
          <span className="label mr-1">Jump to</span>
          {data.days.map((d) => (
            <button key={d.day} type="button" onClick={() => fit(d.ids)} className={`mono ${button} px-1.5 py-0.5`}>
              {d.day} <span className="text-faint">×{d.ids.length}</span>
            </button>
          ))}
        </div>
      </div>

      {/* The same graph in words, for screen readers and for search. */}
      <ul className="sr-only" aria-label="Graph in words">
        {data.lanes.map((lane) => (
          <li key={lane.label}>
            {lane.label}: {lane.count} copies{lane.derivedFrom ? `, ${lane.derivedFrom}` : ""}.
          </li>
        ))}
        {data.links.map((l) => {
          const a = model.sightings.find((s) => s.id === l.source);
          const b = model.sightings.find((s) => s.id === l.target);
          return (
            <li key={`${l.source}-${l.target}-${l.kind}`}>
              {a?.domain} to {b?.domain}: {l.label}.
            </li>
          );
        })}
      </ul>
    </div>
  );
}
