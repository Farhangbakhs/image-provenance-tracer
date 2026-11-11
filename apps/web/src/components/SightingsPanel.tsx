"use client";

import { Panel } from "@/components/Panel";
import { API_URL, type RunSightingsOut, type SightingOut } from "@/lib/api/client";
import { useRunSightings } from "@/lib/api/hooks";
import { EARLIEST_DISCLAIMER, SIGNAL_LABEL } from "@/lib/copy";
import { formatInterval, formatUtc } from "@/lib/time";
import { searchProblem } from "@/lib/search-problem";

const CONFIDENCE_CLASS: Record<string, string> = {
  high: "text-conf-high",
  medium: "text-conf-medium",
  low: "text-conf-low",
  unknown: "text-muted",
};

const MATCH_LABEL: Record<string, string> = {
  exact: "identical file",
  near_duplicate: "same picture",
  derivative: "edited copy",
};


function SightingRow({ sighting, earliest }: { sighting: SightingOut; earliest: boolean }) {
  const edits = (sighting.transform?.edits as string[] | undefined) ?? [];
  return (
    <li
      className={`grid grid-cols-[4.5rem_1fr] gap-3 border-l-2 px-3 py-2 ${earliest ? "border-accent" : "border-transparent"}`}
    >
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src={`${API_URL}${sighting.image_url_local}`}
        alt={`Copy found on ${sighting.domain}`}
        loading="lazy"
        className="h-14 w-18 border border-line object-cover"
      />
      <div className="min-w-0">
        <div className="flex flex-wrap items-baseline gap-x-2">
          {earliest ? <span className="text-[11px] font-semibold uppercase tracking-[0.1em] text-accent">earliest found</span> : null}
          <a
            href={sighting.page_url ?? sighting.image_url}
            target="_blank"
            rel="noopener noreferrer nofollow"
            className="truncate hover:underline"
          >
            {sighting.domain}
          </a>
          <span className="mono text-[11px] text-muted">via {sighting.provider}</span>
        </div>
        {sighting.title ? <div className="truncate text-[12px] text-muted">{sighting.title}</div> : null}
        <div className="mono mt-0.5 text-[12px]">
          {formatInterval(sighting.date_lower, sighting.date_upper)}{" "}
          <span className={CONFIDENCE_CLASS[sighting.date_confidence] ?? "text-muted"}>({sighting.date_confidence})</span>
        </div>
        <div className="text-[11px] text-muted">
          {MATCH_LABEL[sighting.match_class] ?? sighting.match_class}
          {edits.length ? ` · ${edits.join(", ")}` : ""}
          {sighting.deciding
            ? ` · set by ${SIGNAL_LABEL[sighting.deciding.kind] ?? sighting.deciding.kind} (${formatUtc(sighting.deciding.value)})`
            : ""}
        </div>
      </div>
    </li>
  );
}

export function SightingsList({ data }: { data: RunSightingsOut }) {
  const rejected = data.candidates.unrelated + data.candidates.fetch_failed;
  const notes = Object.entries(data.notes);
  const problem = searchProblem(data.notes, data.candidates);
  return (
    <Panel
      title="Sightings"
      aside={`${data.sightings.length} verified · ${rejected} rejected of ${data.sightings.length + rejected + data.candidates.pending} candidates`}
    >
      {data.earliest_sighting_id ? (
        <p className="border-b border-line px-3 py-2 text-[12px] text-muted">{EARLIEST_DISCLAIMER}</p>
      ) : null}
      {problem ? (
        <p role="alert" className="border-b border-line px-3 py-2 text-[12px] font-semibold">
          {problem}
        </p>
      ) : null}
      {data.sightings.length === 0 ? (
        <p className="px-3 py-2 text-[12px] text-muted">
          No verified sightings. A provider hit becomes a sighting only after ORIGIN fetches the image and proves it is
          this picture or an edit of it.
        </p>
      ) : (
        <ol className="divide-y divide-line">
          {data.sightings.map((s) => (
            <SightingRow key={s.id} sighting={s} earliest={s.id === data.earliest_sighting_id} />
          ))}
        </ol>
      )}
      {notes.length ? (
        <ul className="border-t border-line px-3 py-2 text-[11px] text-muted">
          {notes.map(([name, note]) => (
            <li key={name}>
              <span className="mono">{name}</span>: {note}
            </li>
          ))}
        </ul>
      ) : null}
    </Panel>
  );
}

export function SightingsPanel({ runId }: { runId: string }) {
  const { data, error, isPending } = useRunSightings(runId);
  if (isPending) return null;
  if (error || !data) return <Panel title="Sightings"><p className="px-3 py-2 text-[12px]">{error?.message}</p></Panel>;
  return <SightingsList data={data} />;
}
