"use client";

import { useEffect, useMemo, useRef, useState, type KeyboardEvent, type PointerEvent } from "react";

import { Overview, OVERVIEW_H } from "@/components/workspace/Overview";
import type { RunAnalysisOut, SightingOut } from "@/lib/api/client";
import { bareDomain } from "@/lib/domain";
import { buildStories, copyCount, type StoryRow } from "@/lib/stories";
import { isUncertain } from "@/lib/summary";
import { formatDay } from "@/lib/time";
import { axisTicks, layoutRow, placedTime, type Mark } from "@/lib/timeline";
import type { TimelineView } from "@/lib/useTimelineView";
import { fitTimes, outsideCount, panBy, wheelIntent, zoomAt } from "@/lib/viewport";
import type { WorkspaceModel } from "@/lib/workspace";

const LABEL_W = 220;
const ROW_H = 56;
const THIN_H = 48;
const MORE_H = 32;
const AXIS_H = 28;
const PAD = 16;
const HINT_KEY = "origin-zoom-hint";

const ACCENT = "var(--accent)";
const NEUTRAL = "var(--muted)";

const dayOf = (s: SightingOut) => {
  const v = s.date_upper ?? s.date_lower;
  return v ? formatDay(v) : "undated";
};

const confidenceOf = (s: SightingOut) =>
  s.date_confidence === "unknown" ? "date unconfirmed" : `${s.date_confidence} confidence`;

function press(action: () => void) {
  return (event: KeyboardEvent) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      action();
    }
  };
}

/** Move keyboard focus to the neighbouring dot: left and right along a row, up and down between rows. */
function moveFocus(from: Element, key: string): boolean {
  const svg = from.closest("svg");
  if (!svg) return false;
  const marks = [...svg.querySelectorAll<SVGGElement>("[data-mark]")].map((el) => ({
    el,
    row: Number(el.dataset.row),
    x: Number(el.dataset.x),
  }));
  const here = marks.find((m) => m.el === from);
  if (!here) return false;
  let next: (typeof marks)[number] | undefined;
  if (key === "ArrowLeft" || key === "ArrowRight") {
    const same = marks.filter((m) => m.row === here.row).sort((a, b) => a.x - b.x);
    const i = same.indexOf(here);
    next = same[i + (key === "ArrowRight" ? 1 : -1)];
  } else {
    const rows = [...new Set(marks.map((m) => m.row))].sort((a, b) => a - b);
    const target = rows[rows.indexOf(here.row) + (key === "ArrowDown" ? 1 : -1)];
    next = marks.filter((m) => m.row === target).sort((a, b) => Math.abs(a.x - here.x) - Math.abs(b.x - here.x))[0];
  }
  next?.el.focus();
  return next !== undefined;
}

interface Tip {
  x: number;
  y: number;
  text: string;
}

/** The marks of one row: dots for copies, pills for copies too close to tell apart. */
function Marks({
  marks,
  byId,
  color,
  selected,
  y,
  row,
  onSelect,
  onBundle,
  onTip,
}: {
  marks: Mark[];
  byId: Record<string, SightingOut>;
  color: string;
  selected: string | null;
  y: number;
  row: number;
  onSelect: (id: string) => void;
  onBundle: (ids: string[]) => void;
  onTip: (tip: { target: Element; text: string } | null) => void;
}) {
  const nav = (event: KeyboardEvent, act: () => void) => {
    if (event.key.startsWith("Arrow") && moveFocus(event.currentTarget, event.key)) {
      event.preventDefault();
      event.stopPropagation();
    } else press(act)(event);
  };
  return (
    <>
      {marks.map((mark) => {
        if (mark.kind === "pill") {
          const on = selected !== null && mark.ids.includes(selected);
          const act = () => onBundle(mark.ids);
          const dated = mark.ids.map((id) => byId[id]).filter(Boolean);
          const text = `${mark.ids.length} copies · ${dayOf(dated[0])} – ${dayOf(dated[dated.length - 1])}`;
          return (
            <g
              key={mark.ids.join(",")}
              data-mark
              data-row={row}
              data-x={mark.x}
              role="button"
              tabIndex={0}
              aria-label={`${mark.ids.length} copies close together`}
              onClick={act}
              onKeyDown={(e) => nav(e, act)}
              onPointerEnter={(e) => onTip({ target: e.currentTarget, text })}
              onPointerLeave={() => onTip(null)}
              className="cursor-pointer outline-none [&:focus-visible>circle:first-child]:stroke-[var(--accent)]"
            >
              <circle cx={mark.x} cy={y} r={mark.r} fill="var(--surface-2)" stroke={on ? ACCENT : color} strokeWidth={on ? 2 : 1} />
              <text x={mark.x} y={y + 4} textAnchor="middle" fontSize={11} fill="var(--text)" className="tabular-nums" pointerEvents="none">
                {mark.ids.length}
              </text>
            </g>
          );
        }
        const s = byId[mark.id];
        const hollow = isUncertain(s);
        const on = selected === mark.id;
        const act = () => onSelect(mark.id);
        const text = `${bareDomain(s.domain)} · ${dayOf(s)} · ${confidenceOf(s)}`;
        return (
          <g
            key={mark.id}
            data-mark
            data-row={row}
            data-x={mark.x}
            role="button"
            tabIndex={0}
            aria-label={`${bareDomain(s.domain)}, ${dayOf(s)}`}
            aria-pressed={on}
            onClick={act}
            onKeyDown={(e) => nav(e, act)}
            onPointerEnter={(e) => onTip({ target: e.currentTarget, text })}
            onPointerLeave={() => onTip(null)}
            className="cursor-pointer outline-none [&:focus-visible>circle.sel]:stroke-[var(--accent)]"
          >
            {on ? <circle cx={mark.x} cy={y} r={mark.r + 4} fill="none" stroke={ACCENT} strokeWidth={2} /> : null}
            <circle className="sel" cx={mark.x} cy={y} r={mark.r + 4} fill="transparent" stroke="transparent" strokeWidth={2} />
            {mark.first ? <circle cx={mark.x} cy={y} r={mark.r + 3} fill="none" stroke={color} strokeWidth={1} /> : null}
            <circle cx={mark.x} cy={y} r={mark.r} fill={hollow ? "none" : color} stroke={color} strokeWidth={hollow ? 1.5 : 0} />
          </g>
        );
      })}
    </>
  );
}

interface Band {
  key: string;
  y: number;
  h: number;
  kind: "story" | "more" | "uncaptioned";
  row: StoryRow | null;
}

/**
 * The stories as rows on one time axis you can zoom. Only time zooms; the rows stay put. Ctrl or
 * ⌘ with the wheel (or a pinch) zooms around the pointer, dragging empty space pans, plain
 * scrolling still scrolls the page. Dots re-bundle as the window changes, so a bundle opens into
 * its copies as you zoom in, and never overlaps at any zoom.
 */
export function StoryTimeline({
  model,
  analysis,
  selected,
  selectedStory,
  timeline,
  onSelect,
  onSelectStory,
  onSelectGroup,
}: {
  model: WorkspaceModel;
  analysis: RunAnalysisOut | undefined;
  selected: string | null;
  selectedStory: string | null;
  timeline: TimelineView;
  onSelect: (id: string) => void;
  onSelectStory: (id: string) => void;
  onSelectGroup: (ids: string[]) => void;
}) {
  const [showAll, setShowAll] = useState(false);
  const [uncaptionedOpen, setUncaptionedOpen] = useState<boolean | undefined>(undefined);
  const [tip, setTip] = useState<Tip | null>(null);
  const [hint, setHint] = useState(false);
  const stories = useMemo(() => buildStories(model, analysis, showAll), [model, analysis, showAll]);
  // A selected copy is never hidden: its row opens when it is in the collapsed one.
  const selectedHidden = selected !== null && stories.uncaptioned.some((s) => s.id === selected);
  const open = uncaptionedOpen ?? (stories.rows.length === 0 || selectedHidden);

  const [width, setWidth] = useState(640);
  const canvasRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = canvasRef.current;
    if (!el) return;
    const observer = new ResizeObserver(([entry]) => setWidth(Math.max(240, Math.floor(entry.contentRect.width))));
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  const { full, view, set, animateTo } = timeline;
  const [v0, v1] = view;
  const inner = width - 2 * PAD;
  const xOf = (t: number) => PAD + ((t - v0) / (v1 - v0)) * inner;
  const byId = useMemo(() => Object.fromEntries(model.sightings.map((s) => [s.id, s])), [model.sightings]);
  const allTimes = useMemo(
    () => model.sightings.map(placedTime).filter((t): t is number => t !== null),
    [model.sightings],
  );
  const ticks = useMemo(() => axisTicks(view, inner), [view, inner]);

  const marksFor = (copies: SightingOut[], firstId?: string): Mark[] =>
    layoutRow(
      copies
        .map((s) => ({ s, t: placedTime(s) }))
        .filter((c): c is { s: SightingOut; t: number } => c.t !== null && c.t >= v0 && c.t <= v1)
        .map(({ s, t }) => ({ id: s.id, x: xOf(t), first: s.id === firstId })),
    );

  // Rows and their heights, top to bottom. Labels and canvas rows are built from the same list.
  const bands: Band[] = [];
  let y = OVERVIEW_H + AXIS_H;
  const add = (b: Omit<Band, "y">) => {
    bands.push({ ...b, y });
    y += b.h;
  };
  for (const row of stories.shown) add({ key: row.id, h: ROW_H, kind: "story", row });
  if (stories.hidden > 0 || showAll) add({ key: "more", h: MORE_H, kind: "more", row: null });
  if (stories.uncaptioned.length > 0) add({ key: "uncaptioned", h: open ? ROW_H : THIN_H, kind: "uncaptioned", row: null });
  const height = y;

  // Click a bundle: zoom to fit its copies; if they cannot be told apart even then, list them.
  const openBundle = (ids: string[]) => {
    const times = ids.map((id) => placedTime(byId[id])).filter((t): t is number => t !== null);
    const target = fitTimes(times, full);
    const items = ids.map((id) => ({ id, x: PAD + ((placedTime(byId[id]) as number) - target[0]) / (target[1] - target[0]) * inner }));
    if (v1 - v0 <= target[1] - target[0] + 1 || layoutRow(items).length < 2) onSelectGroup(ids);
    else animateTo(target);
  };

  // Pointer: dragging empty space pans; two fingers pinch. Marks handle their own clicks.
  const pointers = useRef(new Map<number, number>());
  const gesture = useRef<{ kind: "pan" | "pinch"; x: number; view: typeof view; dist: number; mid: number } | null>(null);
  const down = (event: PointerEvent<SVGSVGElement>) => {
    if ((event.target as Element).closest("[data-mark]")) return;
    pointers.current.set(event.pointerId, event.clientX);
    event.currentTarget.setPointerCapture(event.pointerId);
    if (pointers.current.size === 2) {
      const [a, b] = [...pointers.current.values()];
      const rect = event.currentTarget.getBoundingClientRect();
      const mid = v0 + (((a + b) / 2 - rect.left - PAD) / inner) * (v1 - v0);
      gesture.current = { kind: "pinch", x: 0, view, dist: Math.max(1, Math.abs(a - b)), mid };
    } else {
      gesture.current = { kind: "pan", x: event.clientX, view, dist: 0, mid: 0 };
    }
  };
  const move = (event: PointerEvent<SVGSVGElement>) => {
    const g = gesture.current;
    if (!g || !pointers.current.has(event.pointerId)) return;
    pointers.current.set(event.pointerId, event.clientX);
    if (g.kind === "pinch" && pointers.current.size === 2) {
      const [a, b] = [...pointers.current.values()];
      set(zoomAt(g.view, Math.abs(a - b) / g.dist, g.mid, full));
    } else if (g.kind === "pan") {
      set(panBy(g.view, -((event.clientX - g.x) / inner) * (g.view[1] - g.view[0]), full));
    }
  };
  const up = (event: PointerEvent<SVGSVGElement>) => {
    pointers.current.delete(event.pointerId);
    gesture.current = null;
  };

  // The wheel: Ctrl or ⌘ zooms around the cursor; a plain wheel scrolls the page and, once,
  // says how to zoom.
  useEffect(() => {
    const el = canvasRef.current;
    if (!el) return;
    const onWheel = (event: WheelEvent) => {
      const intent = wheelIntent(event);
      if (!intent.zoom) {
        let seen = false;
        try {
          seen = sessionStorage.getItem(HINT_KEY) === "1";
          sessionStorage.setItem(HINT_KEY, "1");
        } catch {
          // Storage can be blocked; the hint then shows once per page.
        }
        if (!seen) {
          setHint(true);
          window.setTimeout(() => setHint(false), 2000);
        }
        return;
      }
      event.preventDefault();
      const rect = el.getBoundingClientRect();
      set(zoomAt(view, intent.factor, v0 + ((event.clientX - rect.left - PAD) / inner) * (v1 - v0), full));
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, [view, v0, v1, inner, full, set]);

  // Keyboard: + and - zoom, the arrows pan, 0 resets. Arrows on a focused dot move between dots.
  useEffect(() => {
    const onKey = (event: globalThis.KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (target?.closest("input, textarea, select, [contenteditable]") || event.ctrlKey || event.metaKey || event.altKey) return;
      const centre = (v0 + v1) / 2;
      if (event.key === "+" || event.key === "=") animateTo(zoomAt(view, 1.6, centre, full));
      else if (event.key === "-" || event.key === "_") animateTo(zoomAt(view, 1 / 1.6, centre, full));
      else if (event.key === "0") timeline.reset();
      else if ((event.key === "ArrowLeft" || event.key === "ArrowRight") && !target?.closest("[data-mark]")) {
        event.preventDefault();
        animateTo(panBy(view, (event.key === "ArrowRight" ? 0.2 : -0.2) * (v1 - v0), full));
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [view, v0, v1, full, animateTo, timeline]);

  const showTip = (next: { target: Element; text: string } | null) => {
    const box = canvasRef.current?.getBoundingClientRect();
    if (!next || !box) return setTip(null);
    const r = next.target.getBoundingClientRect();
    setTip({ x: r.left + r.width / 2 - box.left, y: r.top - box.top - 6, text: next.text });
  };

  const dim = (id: string | null) => (selectedStory !== null && selectedStory !== id ? "opacity-60" : "");
  const cell = "border-b border-line";

  return (
    <div className="flex">
      <div className="shrink-0" style={{ width: LABEL_W }}>
        <div className={cell} style={{ height: OVERVIEW_H }} />
        <div className={cell} style={{ height: AXIS_H }} />
        {bands.map((band) => {
          if (band.kind === "story" && band.row) {
            const row = band.row;
            const focused = selectedStory === row.id;
            const outside = outsideCount(row.copies.map(placedTime), view);
            return (
              <button
                key={band.key}
                type="button"
                onClick={() => onSelectStory(row.id)}
                aria-pressed={focused}
                title={`${row.label}\n${row.status} · ${copyCount(row.copies.length)}${row.first ? `\nFirst: ${bareDomain(row.first.domain)} · ${dayOf(row.first)}` : ""}`}
                style={{ height: band.h }}
                className={`${cell} ${dim(row.id)} box-border flex w-full flex-col justify-center gap-0.5 px-4 text-left hover:bg-surface-2 ${
                  focused ? "border-l-2 border-l-accent bg-surface-2" : "border-l-2 border-l-transparent"
                }`}
              >
                <span className="line-clamp-2 text-[13px] leading-tight">{row.label}</span>
                <span className="truncate text-[12px] tabular-nums text-muted">
                  {row.status} · {copyCount(row.copies.length)}
                  {outside > 0 ? ` · ${outside} outside view` : ""}
                </span>
              </button>
            );
          }
          if (band.kind === "more") {
            return (
              <button
                key={band.key}
                type="button"
                onClick={() => setShowAll((v) => !v)}
                style={{ height: band.h }}
                className={`${cell} box-border block w-full px-4 text-left text-[12px] text-muted underline-offset-2 hover:text-text hover:underline`}
              >
                {showAll ? "Show fewer stories" : `${stories.hidden} more ${stories.hidden === 1 ? "story" : "stories"}`}
              </button>
            );
          }
          const outside = outsideCount(stories.uncaptioned.map(placedTime), view);
          return (
            <button
              key={band.key}
              type="button"
              onClick={() => setUncaptionedOpen(!open)}
              aria-expanded={open}
              style={{ height: band.h }}
              className={`${cell} box-border flex w-full flex-col justify-center gap-0.5 border-l-2 border-l-transparent px-4 text-left hover:bg-surface-2`}
            >
              <span className="line-clamp-2 text-[13px] leading-tight">
                {stories.rows.length === 0 ? "No readable captions" : "No readable caption"}
              </span>
              <span className="truncate text-[12px] tabular-nums text-muted">
                {copyCount(stories.uncaptioned.length)}
                {outside > 0 ? ` · ${outside} outside view` : ""} · {open ? "Hide" : "Show"}
              </span>
            </button>
          );
        })}
      </div>

      <div ref={canvasRef} className="relative min-w-0 flex-1">
        <div className={cell}>
          <Overview times={allTimes} full={full} view={view} width={width} pad={PAD} onView={set} />
        </div>
        <svg
          width={width}
          height={height - OVERVIEW_H}
          role="group"
          aria-label="Timeline. Ctrl and scroll zooms, drag pans."
          data-testid="timeline"
          style={{ touchAction: "pan-y", cursor: "grab" }}
          onPointerDown={down}
          onPointerMove={move}
          onPointerUp={up}
          onPointerCancel={up}
        >
          <line x1={0} x2={width} y1={AXIS_H - 0.5} y2={AXIS_H - 0.5} stroke="var(--line)" />
          {ticks.map((t) => (
            <g key={t.x}>
              <line x1={PAD + t.x} x2={PAD + t.x} y1={AXIS_H - 6} y2={AXIS_H - 1} stroke="var(--line)" />
              <text x={PAD + t.x} y={AXIS_H - 10} textAnchor="middle" fontSize={12} fill="var(--muted)" className="tabular-nums">
                {t.label}
              </text>
            </g>
          ))}
          {bands.map((band, index) => {
            const top = band.y - OVERVIEW_H;
            const divider = <line x1={0} x2={width} y1={top + band.h - 0.5} y2={top + band.h - 0.5} stroke="var(--line)" />;
            if (band.kind === "more") return <g key={band.key}>{divider}</g>;
            if (band.kind === "story" && band.row) {
              const row = band.row;
              return (
                <g key={band.key} className={dim(row.id)} role="group" aria-label={`${row.label}: ${copyCount(row.copies.length)}`}>
                  <Marks
                    marks={marksFor(row.copies, row.first?.id)}
                    byId={byId}
                    color={row.root ? ACCENT : NEUTRAL}
                    selected={selected}
                    y={top + ROW_H / 2}
                    row={index}
                    onSelect={onSelect}
                    onBundle={openBundle}
                    onTip={showTip}
                  />
                  {divider}
                </g>
              );
            }
            return (
              <g key={band.key} role="group" aria-label="Copies with no readable caption">
                {open ? (
                  <Marks
                    marks={marksFor(stories.uncaptioned)}
                    byId={byId}
                    color={NEUTRAL}
                    selected={selected}
                    y={top + ROW_H / 2}
                    row={index}
                    onSelect={onSelect}
                    onBundle={openBundle}
                    onTip={showTip}
                  />
                ) : (
                  stories.uncaptioned
                    .filter((s) => (placedTime(s) ?? v0 - 1) >= v0 && (placedTime(s) ?? v1 + 1) <= v1)
                    .map((s) => (
                      <line
                        key={s.id}
                        x1={xOf(placedTime(s) as number)}
                        x2={xOf(placedTime(s) as number)}
                        y1={top + 14}
                        y2={top + THIN_H - 14}
                        stroke="var(--muted)"
                        strokeOpacity={0.45}
                      />
                    ))
                )}
                {divider}
              </g>
            );
          })}
        </svg>
        {tip ? (
          <div
            role="tooltip"
            className="pointer-events-none absolute z-10 -translate-x-1/2 -translate-y-full whitespace-nowrap border border-line bg-surface-2 px-2 py-0.5 text-[12px] tabular-nums"
            style={{ left: tip.x, top: tip.y }}
          >
            {tip.text}
          </div>
        ) : null}
        <div
          aria-live="polite"
          className={`pointer-events-none absolute left-1/2 -translate-x-1/2 border border-line bg-surface-2 px-2 py-1 text-[12px] text-muted transition-opacity duration-150 motion-reduce:transition-none ${
            hint ? "opacity-100" : "opacity-0"
          }`}
          style={{ top: OVERVIEW_H + AXIS_H + 8 }}
        >
          {hint ? "Ctrl + scroll to zoom" : ""}
        </div>
      </div>
    </div>
  );
}
