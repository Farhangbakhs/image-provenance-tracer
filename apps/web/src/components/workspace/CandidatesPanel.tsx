"use client";

import { useMemo } from "react";

import { FoldPanel } from "@/components/Panel";
import { API_URL, type CandidateOut } from "@/lib/api/client";
import { useRunCandidates } from "@/lib/api/hooks";
import { readCandidate, reasonGroup } from "@/lib/candidates";

function Row({ candidate }: { candidate: CandidateOut }) {
  const { headline, facts } = readCandidate(candidate);
  return (
    <li className="px-3 py-2">
      <details>
        <summary className="grid cursor-pointer grid-cols-[2.5rem_9rem_1fr] gap-3 hover:text-text">
          <span className="mono text-muted">#{candidate.rank ?? "–"}</span>
          <span className="truncate">{candidate.source ?? "unknown source"}</span>
          <span className="text-muted">{headline}</span>
        </summary>
        <div className="mt-2 grid gap-1 pl-[3.25rem] text-[12px]">
          {candidate.title ? <p className="text-muted">{candidate.title}</p> : null}
          {candidate.reason ? (
            <p>
              <span className="label mr-2">Verdict</span>
              <span className="mono">{candidate.reason}</span>
            </p>
          ) : null}
          {facts.map((f) => (
            <p key={f.label}>
              <span className="label mr-2">{f.label}</span>
              <span className="mono break-all">{f.value}</span>
            </p>
          ))}
          {candidate.provider_url ? (
            <p>
              <span className="label mr-2">Provider link</span>
              <span className="mono break-all text-muted">{candidate.provider_url}</span>
            </p>
          ) : null}
          {candidate.page_local ? (
            <p>
              <a href={`${API_URL}${candidate.page_local}`} target="_blank" rel="noreferrer" className="underline hover:text-text">
                View the stored page (plain text)
              </a>
            </p>
          ) : null}
        </div>
      </details>
    </li>
  );
}

/** The hits ORIGIN checked but could not turn into copies, and the ones it never opened. */
export function CandidatesPanel({ runId }: { runId: string }) {
  const { data } = useRunCandidates(runId);
  // The set-aside hits grouped by why, biggest group first.
  const groups = useMemo(() => {
    const by = new Map<string, CandidateOut[]>();
    for (const c of data?.rejected ?? []) {
      const key = reasonGroup(c.reason);
      by.set(key, [...(by.get(key) ?? []), c]);
    }
    return [...by.entries()].sort((a, b) => b[1].length - a[1].length);
  }, [data]);
  if (!data || (data.rejected.length === 0 && data.unchecked.length === 0)) return null;
  return (
    <>
      {data.rejected.length > 0 ? (
        <FoldPanel
          title={`Checked, not matched (${data.rejected.length})`}
          note={groups.map(([reason, items]) => `${items.length} ${reason}`).join(" · ")}
        >
          <p className="border-b border-line px-3 py-2 text-[13px] text-muted">
            Hits the search engine returned that did not become copies, grouped by why.
          </p>
          {groups.map(([reason, items]) => (
            <details key={reason} className="border-b border-line last:border-b-0">
              <summary className="flex cursor-pointer justify-between gap-3 px-3 py-2 text-[13px] hover:bg-surface-2">
                <span>{reason}</span>
                <span className="tabular-nums text-muted">{items.length}</span>
              </summary>
              <ul className="divide-y divide-line border-t border-line text-[13px]">
                {items.map((c) => (
                  <Row key={c.id} candidate={c} />
                ))}
              </ul>
            </details>
          ))}
        </FoldPanel>
      ) : null}
      {data.unchecked.length > 0 ? (
        <FoldPanel
          title={`Not checked (${data.unchecked.length})`}
          note={`ranked below the ${data.check_limit} best hits, so never opened`}
        >
          <p className="border-b border-line px-3 py-2 text-[13px] text-muted">
            ORIGIN opens the {data.check_limit} best-ranked hits of a trace, to keep its memory and time bounded. These ranked
            lower and were not opened, so nothing is known about them.
          </p>
          <div className="text-[13px]">
            <ul className="divide-y divide-line">
              {data.unchecked.map((c) => (
                <li key={c.id} className="grid grid-cols-[2.5rem_9rem_1fr] gap-3 px-3 py-1.5">
                  <span className="mono text-muted">#{c.rank ?? "–"}</span>
                  <span className="truncate">{c.source ?? "unknown source"}</span>
                  <span className="truncate text-muted" title={c.title ?? undefined}>
                    {c.title ?? c.provider_url}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        </FoldPanel>
      ) : null}
    </>
  );
}
