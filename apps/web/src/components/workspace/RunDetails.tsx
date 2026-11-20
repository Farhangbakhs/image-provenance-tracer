"use client";

import { useMemo } from "react";

import { Panel } from "@/components/Panel";
import type { RunSightingsOut } from "@/lib/api/client";
import { useRunCandidates } from "@/lib/api/hooks";
import { reasonGroup } from "@/lib/candidates";

/**
 * What the search returned and what became of it: every count behind the answer, with the
 * reasons hits were set aside. Opens in the side panel from the summary's "details".
 */
export function RunDetails({
  runId,
  counts,
  onClose,
}: {
  runId: string;
  counts: RunSightingsOut["candidates"];
  onClose: () => void;
}) {
  const { data } = useRunCandidates(runId);
  const reasons = useMemo(() => {
    const tally = new Map<string, number>();
    for (const c of data?.rejected ?? []) {
      const key = reasonGroup(c.reason);
      tally.set(key, (tally.get(key) ?? 0) + 1);
    }
    return [...tally.entries()].sort((a, b) => b[1] - a[1]);
  }, [data]);
  const checked = counts.verified + counts.unrelated + counts.fetch_failed + counts.blocked;
  const rows: Array<[string, number]> = [
    ["Search results", checked + counts.pending],
    ["Checked by ORIGIN", checked],
    ["Verified copies of your picture", counts.verified],
    ["Not your picture", counts.unrelated],
    ["Page could not be read", counts.fetch_failed],
    ["Blocked by a Google redirect page", counts.blocked],
    [`Not checked (limit of ${data?.check_limit ?? 50} per trace)`, counts.pending],
  ];
  return (
    <aside aria-label="Run details" className="flex flex-col gap-3">
      <Panel
        title="Run details"
        aside={
          <button type="button" onClick={onClose} aria-label="Close details" className="border border-line px-2 hover:border-text">
            ✕
          </button>
        }
      >
        <dl className="divide-y divide-line text-[12px]">
          {rows.map(([label, n]) => (
            <div key={label} className="flex justify-between gap-3 px-3 py-1.5">
              <dt className="text-muted">{label}</dt>
              <dd className="tabular-nums">{n}</dd>
            </div>
          ))}
        </dl>
        {reasons.length > 0 ? (
          <div className="border-t border-line px-3 py-2 text-[12px]">
            <p className="label mb-1">Why hits were set aside</p>
            <ul className="space-y-1">
              {reasons.map(([reason, n]) => (
                <li key={reason} className="flex justify-between gap-3">
                  <span className="text-muted">{reason}</span>
                  <span className="tabular-nums">{n}</span>
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </Panel>
    </aside>
  );
}
