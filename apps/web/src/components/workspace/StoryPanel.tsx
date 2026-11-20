"use client";

import { Panel } from "@/components/Panel";
import type { SightingOut } from "@/lib/api/client";
import { bareDomain } from "@/lib/domain";
import { copyCount, type StoryRow } from "@/lib/stories";
import { formatDay } from "@/lib/time";

function CopiesList({
  copies,
  selected,
  onSelect,
}: {
  copies: SightingOut[];
  selected: string | null;
  onSelect: (id: string) => void;
}) {
  return (
    <ul className="divide-y divide-line text-[12px]">
      {copies.map((s) => {
        const day = s.date_upper ?? s.date_lower;
        return (
          <li key={s.id}>
            <button
              type="button"
              onClick={() => onSelect(s.id)}
              aria-pressed={selected === s.id}
              className={`grid w-full grid-cols-[1fr_auto_auto] items-baseline gap-3 px-3 py-1.5 text-left hover:bg-surface-2 ${
                selected === s.id ? "border-l-2 border-l-accent bg-surface-2" : "border-l-2 border-l-transparent"
              }`}
            >
              <span className="truncate">{bareDomain(s.domain)}</span>
              <span className="tabular-nums text-muted">{day ? formatDay(day) : "undated"}</span>
              <span className="mono tabular-nums text-muted" title="Source reliability (A to F) and credibility (1 to 6)">
                {s.reliability ?? "F"}
                {s.credibility ?? "–"}
              </span>
            </button>
          </li>
        );
      })}
    </ul>
  );
}

function CloseButton({ label, onClose }: { label: string; onClose: () => void }) {
  return (
    <button type="button" onClick={onClose} aria-label={label} className="border border-line px-2 hover:border-text">
      ✕
    </button>
  );
}

/** One story: what it says, why it counts as a contradiction, and its copies, oldest first. */
export function StoryPanel({
  row,
  selected,
  onSelect,
  onClose,
}: {
  row: StoryRow;
  selected: string | null;
  onSelect: (id: string) => void;
  onClose: () => void;
}) {
  return (
    <aside aria-label="Story" className="flex flex-col gap-3">
      <Panel title={row.status} aside={<CloseButton label="Close story" onClose={onClose} />}>
        <div className="flex flex-col gap-2 px-3 py-3 text-[12px]">
          <p className="text-[13px] font-medium">{row.label}</p>
          {row.summary ? <p className="text-muted">{row.summary}</p> : null}
          {row.reason ? (
            <p>
              <span className="label mr-2">Why it contradicts the original</span>
              <span className="text-muted">{row.reason}</span>
            </p>
          ) : null}
        </div>
        <p className="label border-t border-line px-3 pt-2">{copyCount(row.copies.length)}, oldest first</p>
        <CopiesList copies={row.copies} selected={selected} onSelect={onSelect} />
      </Panel>
    </aside>
  );
}

/** Copies too close in time to tell apart on the timeline, listed instead. */
export function GroupPanel({
  copies,
  selected,
  onSelect,
  onClose,
}: {
  copies: SightingOut[];
  selected: string | null;
  onSelect: (id: string) => void;
  onClose: () => void;
}) {
  return (
    <aside aria-label="Copies close together" className="flex flex-col gap-3">
      <Panel title="Copies close together" aside={<CloseButton label="Close list" onClose={onClose} />}>
        <p className="border-b border-line px-3 py-2 text-[12px] text-muted">
          These {copies.length} copies were found within the same moment, so the timeline cannot separate them.
        </p>
        <CopiesList copies={copies} selected={selected} onSelect={onSelect} />
      </Panel>
    </aside>
  );
}
