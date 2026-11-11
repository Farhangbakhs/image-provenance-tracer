"use client";

import { forceCollide, forceManyBody, forceX, forceY } from "d3-force";
import dynamic from "next/dynamic";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type ForceGraphComponent from "react-force-graph-2d";
import type { ForceGraphMethods, LinkObject, NodeObject } from "react-force-graph-2d";

import { API_URL, type RunAnalysisOut } from "@/lib/api/client";
import { explainDate, explainMatch } from "@/lib/explain";
import { buildLineageGraph, neighbourhood, placedAt, type GraphLink, type GraphNode } from "@/lib/lineage-graph";
import { formatInterval } from "@/lib/time";
import type { WorkspaceModel } from "@/lib/workspace";

// The graph draws on a canvas in the browser; it has nothing to render on the server.
const ForceGraph2D = dynamic(() => import("react-force-graph-2d"), { ssr: false }) as unknown as typeof ForceGraphComponent;

type Node = NodeObject<GraphNode>;
type Link = LinkObject<GraphNode, GraphLink>;

const NODE = 40; // thumbnail side, in world units
const MIN_SCREEN = 28; // and never smaller than this many pixels on screen
const HEIGHT = 560;

/** Colours from the design tokens, read once from CSS so the canvas matches the console. */
function palette() {
  const css = getComputedStyle(document.documentElement);
  const v = (name: string, fallback: string) => css.getPropertyValue(name).trim() || fallback;
  return {
    bg: v("--bg", "#111418"),
    line: v("--line", "#383e47"),
    surface: v("--surface-2", "#252a31"),
    text: v("--text", "#f6f7f9"),
    muted: v("--muted", "#abb3bf"),
    faint: v("--faint", "#8f99a8"),
    accent: v("--accent", "#f2a93b"),
    intent: v("--intent", "#4c90f0"),
    conf: {
      high: v("--conf-high", "#4fb477"),
      medium: v("--conf-medium", "#c9b458"),
      low: v("--conf-low", "#e07a67"),
      unknown: v("--faint", "#8f99a8"),
    } as Record<string, string>,
  };
}

function endId(end: Link["source"]): string {
  return typeof end === "object" && end !== null ? String((end as Node).id) : String(end);
}

/**
 * The lineage as a living graph, in the manner of Obsidian's graph view: every copy is a node
 * showing its image, pulled to its date on a horizontal time axis and loosely to its variant's
 * band, with links that spring. Drag nodes, scroll to zoom into any date, hover to light up a
 * copy's connections, and go full screen.
 */
export function LineageGraph({
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
  const data = useMemo(() => buildLineageGraph(model, analysis), [model, analysis]);
  const graph = useMemo(() => ({ nodes: data.nodes.map((n) => ({ ...n })), links: data.links.map((l) => ({ ...l })) }), [data]);
  const fg = useRef<ForceGraphMethods<Node, Link> | undefined>(undefined);
  const box = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ width: 900, height: HEIGHT });
  const [full, setFull] = useState(false);
  const [hover, setHover] = useState<string | null>(null);
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

  // Fill the container, in and out of full screen.
  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const observer = new ResizeObserver(([entry]) =>
      setSize({ width: Math.floor(entry.contentRect.width), height: Math.floor(entry.contentRect.height) }),
    );
    observer.observe(el);
    const onFull = () => setFull(document.fullscreenElement === el);
    document.addEventListener("fullscreenchange", onFull);
    return () => {
      observer.disconnect();
      document.removeEventListener("fullscreenchange", onFull);
    };
  }, []);

  // Forces: time holds x firmly, the variant band holds y loosely, the rest is Obsidian-like.
  const configure = useCallback(() => {
    const g = fg.current;
    if (!g) return;
    g.d3Force("x", forceX<Node>((n) => n.timeX).strength(0.85));
    g.d3Force("y", forceY<Node>((n) => n.laneY).strength(0.15));
    g.d3Force("charge", forceManyBody<Node>().strength(-90).distanceMax(320));
    g.d3Force("collide", forceCollide<Node>(NODE * 0.75));
    g.d3Force("center", null);
    const link = g.d3Force("link");
    link?.distance?.((l: Link) => (l.kind === "same" ? 50 : 90));
    link?.strength?.((l: Link) => (l.kind === "same" ? 0.12 : 0.04));
    g.d3ReheatSimulation();
  }, []);

  // The graph component loads lazily, so forces are set on its first frame, and again whenever
  // the data changes; the first settle then fits everything in view.
  const configured = useRef<object | null>(null);
  const fitted = useRef(false);
  useEffect(() => {
    fitted.current = false;
  }, [graph]);

  /** Fit all copies, or one day's: a lone copy is centred at a readable zoom, not filled in. */
  const fit = (ids?: string[], duration = 600) => {
    const g = fg.current;
    if (!g) return;
    if (ids && ids.length === 1) {
      const node = graph.nodes.find((n) => n.id === ids[0]);
      if (node?.x !== undefined && node.y !== undefined) {
        g.centerAt(node.x, node.y, duration);
        g.zoom(3, duration);
      }
      return;
    }
    const set = ids ? new Set(ids) : null;
    g.zoomToFit(duration, 80, set ? (n) => set.has(String(n.id)) : undefined);
    window.setTimeout(() => {
      if ((g.zoom() ?? 1) > 4) g.zoom(4, 300);
    }, duration + 20);
  };

  const toggleFull = () => {
    const el = box.current;
    if (!el) return;
    if (document.fullscreenElement) void document.exitFullscreen();
    else void el.requestFullscreen();
  };

  const drawNode = (node: Node, ctx: CanvasRenderingContext2D, scale: number) => {
    if (!colours || node.x === undefined || node.y === undefined) return;
    const dim = lit !== null && !lit.has(String(node.id));
    const s = node.sighting;
    const side = Math.max(NODE, MIN_SCREEN / scale);
    const half = side / 2;
    ctx.globalAlpha = dim ? 0.18 : 1;
    // Frame: confidence colour; earliest gets the amber ring, selection the blue one.
    ctx.fillStyle = colours.surface;
    ctx.fillRect(node.x - half, node.y - half, side, side);
    const img = images.current.get(String(node.id));
    if (img?.complete && img.naturalWidth > 0) {
      const crop = Math.min(img.naturalWidth, img.naturalHeight);
      const sx = (img.naturalWidth - crop) / 2;
      const sy = (img.naturalHeight - crop) / 2;
      ctx.drawImage(img, sx, sy, crop, crop, node.x - half, node.y - half, side, side);
    }
    ctx.lineWidth = 2 / scale + 1;
    ctx.strokeStyle = colours.conf[s.date_confidence] ?? colours.faint;
    ctx.strokeRect(node.x - half, node.y - half, side, side);
    if (node.earliest || String(node.id) === selected || String(node.id) === hover) {
      ctx.lineWidth = 3 / scale + 1.2;
      ctx.strokeStyle = node.earliest ? colours.accent : colours.intent;
      const ring = 4 / scale + 1;
      ctx.strokeRect(node.x - half - ring, node.y - half - ring, side + 2 * ring, side + 2 * ring);
    }
    // Labels fade in as you zoom, as in Obsidian.
    // A small graph is labelled throughout; a big one labels as you zoom in.
    const fade = data.nodes.length <= 15 ? 1 : Math.min(1, Math.max(0, (scale - 0.9) / 0.8));
    const show = Math.max(fade, String(node.id) === hover || node.earliest ? 1 : 0);
    if (show > 0 && !dim) {
      const font = Math.max(10 / scale, 3);
      ctx.globalAlpha = show;
      ctx.font = `${node.earliest ? 600 : 400} ${font}px Inter, system-ui, sans-serif`;
      ctx.textAlign = "center";
      ctx.textBaseline = "top";
      ctx.fillStyle = node.earliest ? colours.accent : colours.muted;
      const name = s.domain.replace(/^www\./, "");
      ctx.fillText(node.earliest ? `earliest · ${name}` : name, node.x, node.y + half + 4 / scale + 2);
      if (fade > 0.5 && placedAt(s)) {
        ctx.fillStyle = colours.faint;
        ctx.font = `${Math.max(9 / scale, 2.6)}px "JetBrains Mono", ui-monospace, monospace`;
        ctx.fillText((placedAt(s) as string).slice(0, 10), node.x, node.y + half + 4 / scale + 2 + font * 1.3);
      }
    }
    ctx.globalAlpha = 1;
  };

  const drawLinkLabel = (link: Link, ctx: CanvasRenderingContext2D, scale: number) => {
    if (!colours || !link.label || scale < 0.8) return;
    const a = link.source as Node;
    const b = link.target as Node;
    if (a.x === undefined || b.x === undefined || a.y === undefined || b.y === undefined) return;
    const dim = lit !== null && !(lit.has(String(a.id)) && lit.has(String(b.id)));
    if (dim) return;
    ctx.font = `${Math.max(10 / scale, 3)}px Inter, system-ui, sans-serif`;
    ctx.textAlign = "center";
    ctx.textBaseline = "bottom";
    ctx.fillStyle = link.kind === "forward" ? colours.intent : colours.muted;
    ctx.fillText(link.label, (a.x + b.x) / 2, (a.y + b.y) / 2 - 3 / scale);
  };

  // The time axis and the variant bands, redrawn for whatever part of the world is on screen.
  const drawAxis = (ctx: CanvasRenderingContext2D, scale: number) => {
    const g = fg.current;
    if (!colours || !g) return;
    if (configured.current !== graph) {
      configured.current = graph;
      configure();
    }
    const topLeft = g.screen2GraphCoords(0, 0);
    const bottomRight = g.screen2GraphCoords(size.width, size.height);
    const visible = data.scale.copy().domain([data.scale.invert(topLeft.x), data.scale.invert(bottomRight.x)]);
    const ticks = visible.ticks(Math.max(2, Math.floor(size.width / 140)));
    const format = visible.tickFormat(Math.max(2, Math.floor(size.width / 140)));
    ctx.save();
    ctx.lineWidth = 1 / scale;
    ctx.setLineDash([3 / scale, 4 / scale]);
    ctx.strokeStyle = colours.line;
    ctx.fillStyle = colours.faint;
    ctx.font = `${11 / scale}px "JetBrains Mono", ui-monospace, monospace`;
    ctx.textAlign = "center";
    ctx.textBaseline = "top";
    for (const t of ticks) {
      const x = data.scale(t);
      ctx.beginPath();
      ctx.moveTo(x, topLeft.y + 22 / scale);
      ctx.lineTo(x, bottomRight.y);
      ctx.stroke();
      ctx.fillText(format(t), x, topLeft.y + 6 / scale);
    }
    ctx.setLineDash([]);
    ctx.textAlign = "left";
    ctx.textBaseline = "middle";
    for (const lane of data.lanes) {
      ctx.fillStyle = colours.text;
      ctx.font = `600 ${12 / scale}px "JetBrains Mono", ui-monospace, monospace`;
      ctx.fillText(lane.label, topLeft.x + 10 / scale, lane.y - 8 / scale);
      ctx.fillStyle = colours.faint;
      ctx.font = `${10 / scale}px Inter, system-ui, sans-serif`;
      ctx.fillText(
        `${lane.count} cop${lane.count === 1 ? "y" : "ies"}${lane.derivedFrom ? ` · ${lane.derivedFrom}` : ""}`,
        topLeft.x + 10 / scale,
        lane.y + 8 / scale,
      );
    }
    ctx.restore();
  };

  const current = model.sightings.find((s) => s.id === selected) ?? null;
  const linkColour = (l: Link) => {
    if (!colours) return "#555";
    const dim = lit !== null && !(lit.has(endId(l.source)) && lit.has(endId(l.target)));
    const base = l.kind === "forward" ? colours.intent : l.kind === "same" ? colours.line : colours.muted;
    return dim ? `${base}33` : base;
  };

  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-2 px-3 py-2 text-[13px] text-muted">
        <span>
          Each image is a copy, placed at the earliest date its evidence allows, claims included; the amber
          &ldquo;earliest found&rdquo; counts only what is proven. Drag to pan, scroll to zoom into a date, hover to light
          up a copy&rsquo;s links, click to open its evidence.
        </span>
        <span className="flex gap-2">
          <button type="button" onClick={() => fit()} className="border border-line px-2 py-0.5 text-[12px] hover:border-intent hover:text-text">
            Fit all
          </button>
          <button type="button" onClick={toggleFull} className="border border-line px-2 py-0.5 text-[12px] hover:border-intent hover:text-text">
            {full ? "Exit full screen" : "Full screen"}
          </button>
        </span>
      </div>

      <div
        ref={box}
        className="relative w-full overflow-hidden border-y border-line bg-bg"
        style={{ height: full ? "100vh" : HEIGHT }}
        aria-label="Lineage graph: copies of the picture over time"
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
            linkWidth={(l) => (l.kind === "same" ? 1 : 1.6)}
            linkLineDash={(l) => (l.kind === "forward" ? [5, 4] : null)}
            linkDirectionalArrowLength={(l) => (l.kind === "same" ? 0 : 6)}
            linkDirectionalArrowRelPos={0.92}
            linkDirectionalArrowColor={linkColour}
            linkCurvature={(l) => (l.kind === "forward" ? 0.25 : 0)}
            linkCanvasObjectMode={() => "after"}
            linkCanvasObject={drawLinkLabel}
            onRenderFramePre={drawAxis}
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

        <ul className="pointer-events-none absolute bottom-2 right-2 flex flex-wrap gap-x-4 gap-y-1 border border-line bg-surface-1/90 px-2 py-1 text-[12px] text-muted">
          <li className="flex items-center gap-1.5">
            <span className="inline-block size-2.5 border-2 border-accent" /> earliest found
          </li>
          <li className="flex items-center gap-1.5">
            frame: <span className="inline-block size-2.5 border-2 border-conf-high" /> high
            <span className="inline-block size-2.5 border-2 border-conf-medium" /> medium
            <span className="inline-block size-2.5 border-2 border-conf-low" /> low confidence
          </li>
          <li className="flex items-center gap-1.5">
            <span className="inline-block w-5 border-t border-muted" /> edit made from
          </li>
          <li className="flex items-center gap-1.5">
            <span className="inline-block w-5 border-t-2 border-dashed border-intent" /> Telegram forward
          </li>
        </ul>

        {full && current ? (
          <aside className="absolute right-3 top-3 w-80 border border-line bg-surface-1 p-3 text-[13px]" aria-label="Selected copy">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={`${API_URL}${current.image_url_local}`} alt={`Copy on ${current.domain}`} className="mb-2 max-h-48 w-full border border-line object-contain" />
            <p className="font-semibold">{current.domain}</p>
            <p className="mt-1 text-muted">{explainMatch(current)}</p>
            <p className="mt-1 text-muted">{explainDate(current)}</p>
            <button
              type="button"
              onClick={() => void document.exitFullscreen()}
              className="mt-2 border border-line px-2 py-0.5 text-[12px] hover:border-intent"
            >
              Open full evidence
            </button>
          </aside>
        ) : null}
      </div>

      <div className="flex flex-wrap items-center gap-1.5 px-3 py-2 text-[12px]" aria-label="Zoom to a date">
        <span className="label mr-1">Zoom to a date</span>
        {data.days.map((d) => (
          <button
            key={d.day}
            type="button"
            onClick={() => fit(d.ids)}
            className="mono border border-line px-1.5 py-0.5 text-muted hover:border-intent hover:text-text"
          >
            {d.day} <span className="text-faint">×{d.ids.length}</span>
          </button>
        ))}
      </div>

      {/* The same graph in words, for screen readers and for search. */}
      <ul className="sr-only" aria-label="Lineage in words">
        {data.lanes.map((lane) => (
          <li key={lane.label}>
            Variant {lane.label}: {lane.count} copies{lane.derivedFrom ? `, ${lane.derivedFrom}` : ""}.
          </li>
        ))}
        {data.links
          .filter((l) => l.kind !== "same")
          .map((l) => {
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
