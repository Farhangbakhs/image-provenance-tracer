"use client";

import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";

import type { RunAnalysisOut, SightingOut } from "@/lib/api/client";
import { buildStories, copyCount, type StoryRow } from "@/lib/stories";
import { isUncertain } from "@/lib/summary";
import { formatDay } from "@/lib/time";
import { axisTicks, fitDomain, layoutRow, placedTime, type Mark } from "@/lib/timeline";
import type { WorkspaceModel } from "@/lib/workspace";

const LABEL_W = 220;
const ROW_H = 56;
const THIN_H = 48;
const AXIS_H = 28;
const PAD = 16;

const ACCENT = "var(--accent)";
const NEUTRAL = "var(--muted)";

const when = (s: SightingOut) => (s.date_upper ?? s.date_lower ? formatDay((s.date_upper ?? s.date_lower) as string) : "undated");

function press(action: () => void) {
  return (event: KeyboardEvent) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      action();
    }
  };
}

/** The marks of one row: dots for copies, pills for copies too close to tell apart. */
function Marks({
  marks,
  byId,
  color,
  selected,
  y,
  onSelect,
  onPill,
}: {
  marks: Mark[];
  byId: Record<string, SightingOut>;
  color: string;
  selected: string | null;
  y: number;
  onSelect: (id: string) => void;
  onPill: (ids: string[]) => void;
}) {
  return (
    <>
      {marks.map((mark) => {
        if (mark.kind === "pill") {
          const on = selected !== null && mark.ids.includes(selected);
          const act = () => onPill(mark.ids);
          return (
            <g
              key={mark.ids.join(",")}
              role="button"
              tabIndex={0}
              aria-label={`${mark.ids.length} copies close together`}
              onClick={act}
              onKeyDown={press(act)}
              className="cursor-pointer outline-none [&:focus-visible>circle:first-child]:stroke-[var(--accent)]"
            >
              <title>{`${mark.ids.length} copies`}</title>
              <circle cx={mark.x} cy={y} r={mark.r} fill="var(--surface-2)" stroke={on ? ACCENT : color} strokeWidth={on ? 2 : 1} />
              <text x={mark.x} y={y + 4} textAnchor="middle" fontSize={11} fill="var(--text)" className="tabular-nums">
                {mark.ids.length}
              </text>
            </g>
          );
        }
        const s = byId[mark.id];
        const hollow = isUncertain(s);
        const on = selected === mark.id;
        const act = () => onSelect(mark.id);
        return (
          <g
            key={mark.id}
            role="button"
            tabIndex={0}
            aria-label={`${s.domain}, ${when(s)}`}
            aria-pressed={on}
            onClick={act}
            onKeyDown={press(act)}
            className="cursor-pointer outline-none [&:focus-visible>circle.sel]:stroke-[var(--accent)]"
          >
            <title>{`${s.domain} · ${when(s)}`}</title>
            {on ? <circle cx={mark.x} cy={y} r={mark.r + 4} fill="none" stroke={ACCENT} strokeWidth={2} /> : null}
            <circle className="sel" cx={mark.x} cy={y} r={mark.r + 4} fill="transparent" stroke="transparent" strokeWidth={2} />
            {mark.first ? <circle cx={mark.x} cy={y} r={mark.r + 3} fill="none" stroke={color} strokeWidth={1} /> : null}
            <circle
              cx={mark.x}
              cy={y}
              r={mark.r}
              fill={hollow ? "none" : color}
              stroke={color}
              strokeWidth={hollow ? 1.5 : 0}
            />
          </g>
        );
      })}
    </>
  );
}

/**
 * The stories as rows on one time axis: the original first, then each retelling, oldest first.
 * Rows are as tall as each other; copies are dots; the only text on the canvas is the axis and
 * the count on a pill. Everything else lives in the label column and the side panel.
 */
export function StoryTimeline({
  model,
  analysis,
  selected,
  selectedStory,
  onSelect,
  onSelectStory,
}: {
  model: WorkspaceModel;
  analysis: RunAnalysisOut | undefined;
  selected: string | null;
  selectedStory: string | null;
  onSelect: (id: string) => void;
  onSelectStory: (id: string) => void;
}) {
  const [showAll, setShowAll] = useState(false);
  const [uncaptionedOpen, setUncaptionedOpen] = useState<boolean | undefined>(undefined);
  const stories = useMemo(() => buildStories(model, analysis, showAll), [model, analysis, showAll]);
  // A selected copy is never hidden: its row opens when it is in the collapsed one.
  const selectedHidden = selected !== null && stories.uncaptioned.some((s) => s.id === selected);
  const open = uncaptionedOpen ?? (stories.rows.length === 0 || selectedHidden);

  const [width, setWidth] = useState(640);
  const axisRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = axisRef.current;
    if (!el) return;
    const observer = new ResizeObserver(([entry]) => setWidth(Math.max(240, Math.floor(entry.contentRect.width))));
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  const byId = useMemo(() => Object.fromEntries(model.sightings.map((s) => [s.id, s])), [model.sightings]);
  const domain = useMemo(
    () => fitDomain(model.sightings.map(placedTime).filter((t): t is number => t !== null)),
    [model.sightings],
  );
  const inner = width - 2 * PAD;
  const xOf = (s: SightingOut) => {
    const t = placedTime(s);
    return PAD + (t === null ? 0 : ((t - domain[0]) / (domain[1] - domain[0])) * inner);
  };
  const ticks = useMemo(() => axisTicks(domain, inner), [domain, inner]);

  const marksFor = (copies: SightingOut[], firstId?: string): Mark[] =>
    layoutRow(
      copies.filter((s) => placedTime(s) !== null).map((s) => ({ id: s.id, x: xOf(s), first: s.id === firstId })),
    );
  const pill = (row: StoryRow | null) => (ids: string[]) => {
    if (row) onSelectStory(row.id);
    else onSelect(ids[0]);
  };

  const dim = (id: string | null) => (selectedStory !== null && selectedStory !== id ? "opacity-60" : "");
  const cell = "border-b border-line";

  return (
    <div className="grid" style={{ gridTemplateColumns: `${LABEL_W}px minmax(0,1fr)` }}>
      <div className={cell} style={{ height: AXIS_H }} />
      <div ref={axisRef} className={cell}>
        <svg width={width} height={AXIS_H} role="img" aria-label="Time axis">
          {ticks.map((t) => (
            <g key={t.x}>
              <line x1={PAD + t.x} x2={PAD + t.x} y1={AXIS_H - 6} y2={AXIS_H} stroke="var(--line)" />
              <text x={PAD + t.x} y={AXIS_H - 10} textAnchor="middle" fontSize={12} fill="var(--muted)" className="tabular-nums">
                {t.label}
              </text>
            </g>
          ))}
        </svg>
      </div>

      {stories.shown.map((row) => {
        const focused = selectedStory === row.id;
        return (
          <RowFragment key={row.id}>
            <button
              type="button"
              onClick={() => onSelectStory(row.id)}
              aria-pressed={focused}
              title={`${row.label}\n${row.status} · ${copyCount(row.copies.length)}${row.first ? `\nFirst: ${row.first.domain} · ${when(row.first)}` : ""}`}
              style={{ height: ROW_H }}
              className={`${cell} ${dim(row.id)} flex flex-col justify-center gap-0.5 px-4 text-left hover:bg-surface-2 ${
                focused ? "border-l-2 border-l-accent bg-surface-2" : "border-l-2 border-l-transparent"
              }`}
            >
              <span className="line-clamp-2 text-[13px] leading-tight">{row.label}</span>
              <span className="truncate text-[12px] tabular-nums text-muted">
                {row.status} · {copyCount(row.copies.length)}
              </span>
            </button>
            <div className={`${cell} ${dim(row.id)}`}>
              <svg width={width} height={ROW_H} role="group" aria-label={`${row.label}: ${copyCount(row.copies.length)}`}>
                <Marks
                  marks={marksFor(row.copies, row.first?.id)}
                  byId={byId}
                  color={row.root ? ACCENT : NEUTRAL}
                  selected={selected}
                  y={ROW_H / 2}
                  onSelect={onSelect}
                  onPill={pill(row)}
                />
              </svg>
            </div>
          </RowFragment>
        );
      })}

      {stories.hidden > 0 || showAll ? (
        <>
          <button
            type="button"
            onClick={() => setShowAll((v) => !v)}
            className={`${cell} px-4 py-2 text-left text-[12px] text-muted underline-offset-2 hover:text-text hover:underline`}
          >
            {showAll ? "Show fewer stories" : `${stories.hidden} more ${stories.hidden === 1 ? "story" : "stories"}`}
          </button>
          <div className={cell} />
        </>
      ) : null}

      {stories.uncaptioned.length > 0 ? (
        <>
          <button
            type="button"
            onClick={() => setUncaptionedOpen(!open)}
            aria-expanded={open}
            style={{ height: open ? ROW_H : THIN_H }}
            className={`${cell} flex flex-col justify-center gap-0.5 border-l-2 border-l-transparent px-4 text-left hover:bg-surface-2`}
          >
            <span className="line-clamp-2 text-[13px] leading-tight">
              {stories.rows.length === 0 ? "No readable captions" : "No readable caption"}
            </span>
            <span className="truncate text-[12px] tabular-nums text-muted">
              {copyCount(stories.uncaptioned.length)} · {open ? "Hide" : "Show"}
            </span>
          </button>
          <div className={cell}>
            <svg width={width} height={open ? ROW_H : THIN_H} role="group" aria-label="Copies with no readable caption">
              {open ? (
                <Marks
                  marks={marksFor(stories.uncaptioned)}
                  byId={byId}
                  color={NEUTRAL}
                  selected={selected}
                  y={ROW_H / 2}
                  onSelect={onSelect}
                  onPill={pill(null)}
                />
              ) : (
                stories.uncaptioned.map((s) => (
                  <line key={s.id} x1={xOf(s)} x2={xOf(s)} y1={14} y2={THIN_H - 14} stroke="var(--muted)" strokeOpacity={0.45} />
                ))
              )}
            </svg>
          </div>
        </>
      ) : null}
    </div>
  );
}

/** Two grid cells that belong together. */
function RowFragment({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
