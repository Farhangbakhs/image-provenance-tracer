"use client";

import { useMemo, useRef } from "react";

import { clampView, formatRange, histogram, MIN_SPAN, panBy, viewToWindow, windowToView, type View } from "@/lib/viewport";

export const OVERVIEW_H = 40;

type Drag = { mode: "pan" | "left" | "right"; x: number; view: View };

/**
 * The whole date range as a thin density histogram, with the window that is on screen. Drag the
 * window to pan, drag its edges to zoom, click the strip to move the window there. It is the same
 * window as the graph's, so the two always agree.
 */
export function Overview({
  times,
  full,
  view,
  width,
  pad,
  onView,
}: {
  times: number[];
  full: View;
  view: View;
  width: number;
  /** Space kept at each end, so the strip lines up with the graph's axis. */
  pad: number;
  onView: (next: View) => void;
}) {
  const inner = Math.max(1, width - 2 * pad);
  const bins = useMemo(() => histogram(times, full, Math.max(8, Math.floor(inner / 6))), [times, full, inner]);
  const peak = Math.max(1, ...bins);
  const win = viewToWindow(view, full, inner);
  const drag = useRef<Drag | null>(null);
  const span = full[1] - full[0];

  const begin = (mode: Drag["mode"], event: React.PointerEvent) => {
    event.stopPropagation();
    (event.currentTarget as Element).setPointerCapture(event.pointerId);
    drag.current = { mode, x: event.clientX, view };
  };
  const move = (event: React.PointerEvent) => {
    const d = drag.current;
    if (!d) return;
    const dt = ((event.clientX - d.x) / inner) * span;
    if (d.mode === "pan") onView(panBy(d.view, dt, full));
    else if (d.mode === "left") onView(clampView([Math.min(d.view[0] + dt, d.view[1] - MIN_SPAN), d.view[1]], full));
    else onView(clampView([d.view[0], Math.max(d.view[1] + dt, d.view[0] + MIN_SPAN)], full));
  };
  const end = () => {
    drag.current = null;
  };
  const jump = (event: React.PointerEvent<SVGRectElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    const x = event.clientX - rect.left - pad;
    const centred = windowToView(x - win.w / 2, win.w, full, inner);
    onView(clampView(centred, full));
    begin("pan", event);
    drag.current = { mode: "pan", x: event.clientX, view: clampView(centred, full) };
  };

  return (
    <div className="relative" style={{ height: OVERVIEW_H }}>
      <svg
        width={width}
        height={OVERVIEW_H}
        role="group"
        aria-label="Overview of the whole date range. Drag the window to pan, drag its edges to zoom."
        data-testid="overview"
        style={{ touchAction: "none" }}
      >
        <rect x={pad} y={0} width={inner} height={OVERVIEW_H} fill="var(--bg)" onPointerDown={jump} onPointerMove={move} onPointerUp={end} />
        {bins.map((n, i) =>
          n === 0 ? null : (
            <rect
              key={i}
              x={pad + (i / bins.length) * inner}
              y={OVERVIEW_H - 2 - (n / peak) * 14}
              width={Math.max(1, inner / bins.length - 1)}
              height={(n / peak) * 14}
              fill="var(--faint)"
              opacity={0.6}
              pointerEvents="none"
            />
          ),
        )}
        <rect
          data-testid="overview-window"
          x={pad + win.x}
          y={0.5}
          width={Math.max(4, win.w)}
          height={OVERVIEW_H - 1}
          fill="var(--text)"
          fillOpacity={0.07}
          stroke="var(--muted)"
          strokeOpacity={0.6}
          style={{ cursor: "grab" }}
          onPointerDown={(e) => begin("pan", e)}
          onPointerMove={move}
          onPointerUp={end}
        />
        {(["left", "right"] as const).map((side) => (
          <rect
            key={side}
            x={pad + win.x + (side === "left" ? 0 : Math.max(4, win.w)) - 4}
            y={0}
            width={8}
            height={OVERVIEW_H}
            fill="transparent"
            style={{ cursor: "ew-resize" }}
            onPointerDown={(e) => begin(side, e)}
            onPointerMove={move}
            onPointerUp={end}
          />
        ))}
      </svg>
      <span
        data-testid="overview-range"
        className="pointer-events-none absolute left-0 right-0 top-1 truncate text-center text-[12px] tabular-nums text-muted"
      >
        {formatRange(view)}
      </span>
    </div>
  );
}
