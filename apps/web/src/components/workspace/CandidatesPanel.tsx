"use client";

import { Panel } from "@/components/Panel";
import { API_URL, type CandidateOut } from "@/lib/api/client";
import { useRunCandidates } from "@/lib/api/hooks";
import { readCandidate } from "@/lib/candidates";

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
  if (!data || (data.rejected.length === 0 && data.unchecked.length === 0)) return null;
  return (
    <>
      {data.rejected.length > 0 ? (
        <Panel
          title={`Checked, not matched (${data.rejected.length})`}
          hint="Hits the search engine returned that did not become copies, and why."
        >
          <ul className="divide-y divide-line text-[13px]">
            {data.rejected.map((c) => (
              <Row key={c.id} candidate={c} />
            ))}
          </ul>
        </Panel>
      ) : null}
      {data.unchecked.length > 0 ? (
        <Panel
          title={`Not checked (${data.unchecked.length})`}
          hint={`ORIGIN opens the ${data.check_limit} best-ranked hits of a trace, to keep its memory and time bounded. These ranked lower and were not opened, so nothing is known about them.`}
        >
          <details className="text-[13px]">
            <summary className="cursor-pointer px-3 py-2 text-muted hover:text-text">
              Show all {data.unchecked.length} unchecked hits
            </summary>
            <ul className="divide-y divide-line border-t border-line">
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
          </details>
        </Panel>
      ) : null}
    </>
  );
}
