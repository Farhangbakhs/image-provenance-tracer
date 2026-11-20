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

/** The hits ORIGIN checked but could not turn into copies, each with why. */
export function CandidatesPanel({ runId }: { runId: string }) {
  const { data } = useRunCandidates(runId);
  if (!data || data.rejected.length === 0) return null;
  return (
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
  );
}
