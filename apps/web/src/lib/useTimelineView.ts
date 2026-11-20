"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { fitDomain } from "./timeline";
import { animationMs, clampView, defaultView, tweenView, type View } from "./viewport";

export interface TimelineView {
  /** The whole range, padded: the widest the timeline can show. */
  full: View;
  /** What is on screen now. */
  view: View;
  /** The default view: where the page opens and "Reset view" returns. */
  base: View;
  isDefault: boolean;
  /** Direct manipulation (drag, pinch, wheel): follows the pointer with no animation. */
  set: (next: View) => void;
  /** Programmatic change (reset, a bundle click, a key): eases out over about 250 ms. */
  animateTo: (target: View) => void;
  reset: () => void;
}

function prefersReducedMotion(): boolean {
  return typeof window !== "undefined" && typeof window.matchMedia === "function"
    ? window.matchMedia("(prefers-reduced-motion: reduce)").matches
    : false;
}

/**
 * The timeline's one shared window. The main graph and the overview strip both read and write
 * it, so they cannot disagree. Until the reader moves it, the view is the default one and
 * follows the data as it arrives.
 */
export function useTimelineView(times: number[], anchors: number[]): TimelineView {
  const full = useMemo(() => fitDomain(times), [times]);
  const base = useMemo(() => defaultView(times, anchors, full), [times, anchors, full]);
  const [manual, setManual] = useState<View | null>(null);
  const frame = useRef(0);
  const view = manual ?? base;

  const stop = useCallback(() => cancelAnimationFrame(frame.current), []);
  useEffect(() => stop, [stop]);

  const set = useCallback(
    (next: View) => {
      stop();
      setManual(clampView(next, full));
    },
    [full, stop],
  );

  const animateTo = useCallback(
    (target: View) => {
      stop();
      const goal = clampView(target, full);
      const ms = animationMs(prefersReducedMotion());
      if (ms === 0) {
        setManual(goal);
        return;
      }
      const from = view;
      const start = performance.now();
      const tick = (now: number) => {
        const t = (now - start) / ms;
        if (t >= 1) {
          setManual(goal);
          return;
        }
        setManual(tweenView(from, goal, t));
        frame.current = requestAnimationFrame(tick);
      };
      frame.current = requestAnimationFrame(tick);
    },
    [full, stop, view],
  );

  const reset = useCallback(() => {
    stop();
    const ms = animationMs(prefersReducedMotion());
    if (ms === 0) {
      setManual(null);
      return;
    }
    const from = view;
    const start = performance.now();
    const tick = (now: number) => {
      const t = (now - start) / ms;
      if (t >= 1) {
        setManual(null);
        return;
      }
      setManual(tweenView(from, base, t));
      frame.current = requestAnimationFrame(tick);
    };
    frame.current = requestAnimationFrame(tick);
  }, [base, stop, view]);

  return { full, view, base, isDefault: manual === null, set, animateTo, reset };
}
