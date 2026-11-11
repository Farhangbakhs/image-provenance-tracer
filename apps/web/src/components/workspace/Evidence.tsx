"use client";

import { useState } from "react";

import { Fields } from "@/components/Panel";
import { Term } from "@/components/ui/Term";
import { API_URL, SNAPSHOT, type ClaimOut, type SightingOut } from "@/lib/api/client";
import { MATCH_LABEL, explainDate, explainGrade, explainMatch } from "@/lib/explain";
import { useOverrule } from "@/lib/api/hooks";
import { formatInterval, formatUtc } from "@/lib/time";
import { SIGNAL_LABEL } from "@/lib/copy";
import { CONFIDENCE_COLOUR, type WorkspaceModel } from "@/lib/workspace";


type SortKey = "date" | "domain" | "match" | "credibility";

export function EvidenceTable({
  model,
  selected,
  onSelect,
}: {
  model: WorkspaceModel;
  selected: string | null;
  onSelect: (id: string) => void;
}) {
  const [sort, setSort] = useState<SortKey>("date");
  const rows = [...model.sightings].sort((a, b) => {
    if (sort === "domain") return a.domain.localeCompare(b.domain);
    if (sort === "match") return a.match_class.localeCompare(b.match_class);
    if (sort === "credibility") return (a.credibility ?? 9) - (b.credibility ?? 9);
    return (a.date_upper ?? "9").localeCompare(b.date_upper ?? "9");
  });
  const header = (key: SortKey, label: string) => (
    <th scope="col" className="px-2 py-1.5 text-left font-normal">
      <button type="button" onClick={() => setSort(key)} className={sort === key ? "text-text" : "text-muted hover:text-text"}>
        {label}
        {sort === key ? " ↓" : ""}
      </button>
    </th>
  );
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-[13px]">
        <thead className="border-b border-line bg-surface-2 text-[11px] uppercase tracking-[0.1em]">
          <tr>
            {header("date", "Date")}
            {header("domain", "Source")}
            {header("match", "Match")}
            <th scope="col" className="px-2 py-1.5 text-left font-normal text-muted">
              Set by
            </th>
            {header("credibility", "Grade (A–F, 1–6)")}
          </tr>
        </thead>
        <tbody className="divide-y divide-line">
          {rows.map((s) => (
            <tr
              key={s.id}
              onClick={() => onSelect(s.id)}
              aria-selected={s.id === selected}
              className={`cursor-pointer ${s.id === selected ? "bg-surface-2" : "hover:bg-surface-2"} ${s.id === model.earliestId ? "border-l-2 border-l-accent" : ""}`}
            >
              <td className="mono px-2 py-1.5">
                {formatInterval(s.date_lower, s.date_upper)}{" "}
                <span style={{ color: CONFIDENCE_COLOUR[s.date_confidence] }}>({s.date_confidence})</span>
              </td>
              <td className="px-2 py-1.5">
                {s.domain}
                {s.analyst_status === "overruled" ? <span className="ml-1 text-muted">(overruled)</span> : null}
              </td>
              <td className="px-2 py-1.5" title={explainMatch(s)}>
                {MATCH_LABEL[s.match_class] ?? s.match_class}
                {s.transform && (s.transform.edits as string[] | undefined)?.length
                  ? <span className="text-muted"> · {(s.transform.edits as string[]).join(", ")}</span>
                  : ""}
              </td>
              <td className="px-2 py-1.5 text-muted">{s.deciding ? SIGNAL_LABEL[s.deciding.kind] ?? s.deciding.kind : "—"}</td>
              <td className="mono px-2 py-1.5" title={explainGrade(s) ?? undefined}>
                {s.reliability ?? "?"}
                {s.credibility ?? "?"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Wipe comparison: drag to reveal the found copy over the query image. */
function Compare({ query, copy }: { query: string; copy: string }) {
  const [split, setSplit] = useState(50);
  return (
    <figure className="border border-line">
      <div className="relative aspect-[4/3] bg-bg">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src={query} alt="Query image" className="absolute inset-0 h-full w-full object-contain" />
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={copy}
          alt="Copy found online"
          className="absolute inset-0 h-full w-full object-contain"
          style={{ clipPath: `inset(0 0 0 ${split}%)` }}
        />
        <div className="absolute inset-y-0 w-px bg-accent" style={{ left: `${split}%` }} aria-hidden />
      </div>
      <figcaption className="flex items-center gap-2 border-t border-line px-2 py-1 text-[11px] text-muted">
        <span>query</span>
        <input
          type="range"
          min={0}
          max={100}
          value={split}
          onChange={(e) => setSplit(Number(e.target.value))}
          aria-label="Compare the query image with the found copy"
          className="flex-1"
        />
        <span>found copy</span>
      </figcaption>
    </figure>
  );
}

function Quote({ text, claim }: { text: string | null; claim: ClaimOut }) {
  if (!text) return <blockquote className="border-l border-line pl-2">{claim.quote}</blockquote>;
  const start = Math.max(0, claim.quote_start - 220);
  const end = Math.min(text.length, claim.quote_end + 220);
  return (
    <blockquote className="border-l border-line pl-2 text-[12px] text-muted">
      {start > 0 ? "…" : ""}
      {text.slice(start, claim.quote_start)}
      <mark className="bg-surface-2 text-text underline decoration-accent">{text.slice(claim.quote_start, claim.quote_end)}</mark>
      {text.slice(claim.quote_end, end)}
      {end < text.length ? "…" : ""}
    </blockquote>
  );
}

export function EvidenceDrawer({
  runId,
  assetDisplayUrl,
  sighting,
  claim,
  earliest,
  onClose,
}: {
  runId: string;
  assetDisplayUrl: string;
  sighting: SightingOut;
  claim: ClaimOut | undefined;
  earliest: boolean;
  onClose: () => void;
}) {
  const overrule = useOverrule(runId);
  const decide = (kind: "claim" | "sighting", id: string, status: "accepted" | "overruled") => {
    const note = status === "overruled" ? window.prompt("Why? (kept in the audit log)") ?? undefined : undefined;
    overrule.mutate({ kind, id, status, note });
  };
  const edits = (sighting.transform?.edits as string[] | undefined) ?? [];

  return (
    <aside aria-label="Evidence" className="flex flex-col gap-3 border border-line bg-surface-1 p-3 lg:sticky lg:top-3 lg:max-h-[calc(100vh-1.5rem)] lg:overflow-y-auto">
      <header className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          {earliest ? <div className="label text-accent">earliest found</div> : null}
          <a href={sighting.page_url ?? sighting.image_url} target="_blank" rel="noopener noreferrer nofollow" className="break-all hover:underline">
            {sighting.page_url ?? sighting.image_url}
          </a>
          {sighting.title ? <div className="text-[12px] text-muted">{sighting.title}</div> : null}
        </div>
        <button type="button" onClick={onClose} className="border border-line px-2 text-[12px] hover:border-text" aria-label="Close evidence">
          ✕
        </button>
      </header>

      <section aria-label="In plain words" className="border border-line border-l-2 border-l-intent bg-surface-2 px-3 py-2 text-[13px]">
        <p>{explainMatch(sighting)}</p>
        <p className="mt-1">{explainDate(sighting)}</p>
        {explainGrade(sighting) ? <p className="mt-1 text-muted">{explainGrade(sighting)}</p> : null}
      </section>

      <Compare query={`${API_URL}${assetDisplayUrl}`} copy={`${API_URL}${sighting.image_url_local}`} />

      <section>
        <h3 className="label mb-1"><Term name="sighting">Match</Term></h3>
        <Fields
          rows={[
            { label: "Class", value: `${MATCH_LABEL[sighting.match_class] ?? sighting.match_class} (${sighting.match_class.replace("_", "-")})${edits.length ? ` · ${edits.join(", ")}` : ""}` },
            { label: "Why", value: sighting.match_reason, mono: true },
            { label: "SSCD", value: sighting.sscd_cosine?.toFixed(3) ?? null, mono: true },
            { label: "pHash / PDQ", value: `${sighting.phash_distance ?? "–"} / ${sighting.pdq_distance ?? "–"} bits`, mono: true },
            { label: "Thresholds", value: sighting.threshold_version, mono: true },
            { label: "Analyst", value: sighting.analyst_status === "overruled" ? `overruled${sighting.analyst_note ? `: ${sighting.analyst_note}` : ""}` : "accepted" },
          ]}
        />
        <div className={SNAPSHOT ? "hidden" : "mt-1 flex gap-2"}>
          <button type="button" className="border border-line px-2 py-0.5 text-[12px] hover:border-text" onClick={() => decide("sighting", sighting.id, sighting.analyst_status === "overruled" ? "accepted" : "overruled")}>
            {sighting.analyst_status === "overruled" ? "Accept match" : "Overrule match"}
          </button>
        </div>
      </section>

      <section>
        <h3 className="label mb-1"><Term name="interval">Date</Term></h3>
        <p className="mono text-[12px]">
          {formatInterval(sighting.date_lower, sighting.date_upper)}{" "}
          <span style={{ color: CONFIDENCE_COLOUR[sighting.date_confidence] }}>({sighting.date_confidence})</span>
        </p>
        <ul className="mt-1 divide-y divide-line border border-line text-[13px]">
          {sighting.evidence.map((e) => (
            <li key={e.id} className="grid grid-cols-[1fr_auto] gap-2 px-2 py-1">
              <span>
                {e.id === sighting.deciding?.id ? <span className="mr-1 text-accent">▸</span> : null}
                {SIGNAL_LABEL[e.kind] ?? e.kind}
                <span className="text-muted"> · {e.bound.replaceAll("_", " ")}</span>
                {typeof e.detail.archive_url === "string" ? (
                  <a href={e.detail.archive_url} target="_blank" rel="noopener noreferrer nofollow" className="ml-1 text-muted underline">
                    archive
                  </a>
                ) : null}
              </span>
              <span className="mono" style={{ color: CONFIDENCE_COLOUR[e.confidence] }}>
                {formatUtc(e.value)}
              </span>
            </li>
          ))}
        </ul>
        <p className="mt-1 text-[12px] text-muted">
          ▸ marks the evidence that set the date. &ldquo;No later than&rdquo; proves the copy existed by then; &ldquo;claimed&rdquo; is
          what a page or file states. Rule {sighting.dating_rule_version}.
        </p>
      </section>

      <section>
        <h3 className="label mb-1"><Term name="narrative">Claim</Term></h3>
        {claim ? (
          <div className="flex flex-col gap-1.5 text-[12px]">
            <p>
              {[claim.event, claim.place, claim.claimed_date].filter(Boolean).join(" · ")}
              {claim.stance && claim.stance !== "asserts" ? <span className="text-muted"> ({claim.stance})</span> : null}
            </p>
            <Quote text={sighting.extracted_text ?? null} claim={claim} />
            {claim.translation ? <p className="text-muted">Translation: {claim.translation}</p> : null}
            <p className="mono text-[11px] text-muted">
              extracted by {claim.llm_provider} {claim.llm_model} · {claim.prompt_version}
              {claim.analyst_status === "overruled" ? ` · overruled${claim.analyst_note ? `: ${claim.analyst_note}` : ""}` : ""}
            </p>
            <div className={SNAPSHOT ? "hidden" : ""}>
              <button type="button" className="border border-line px-2 py-0.5 hover:border-text" onClick={() => decide("claim", claim.id, claim.analyst_status === "overruled" ? "accepted" : "overruled")}>
                {claim.analyst_status === "overruled" ? "Accept claim" : "Overrule claim"}
              </button>
            </div>
          </div>
        ) : (
          <p className="text-[12px] text-muted">No claim was read from this page.</p>
        )}
      </section>

      <section>
        <h3 className="label mb-1"><Term name="credibility">Grade</Term></h3>
        <p className="mono text-[12px]">
          {sighting.reliability ?? "?"}
          {sighting.credibility ?? "?"}
        </p>
        <p className="text-[12px] text-muted">{sighting.grade_rationale}</p>
      </section>
      {overrule.error ? <p role="alert" className="text-[12px]">{overrule.error.message}</p> : null}
    </aside>
  );
}
