"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { Panel } from "@/components/Panel";
import { EvidenceDrawer, EvidenceTable } from "@/components/workspace/Evidence";
import { Timeline } from "@/components/workspace/Timeline";
import { LineageGraph } from "@/components/workspace/LineageGraph";
import { Term } from "@/components/ui/Term";
import { API_URL, SNAPSHOT } from "@/lib/api/client";
import { useAsset, useRun, useRunAnalysis, useRunSightings } from "@/lib/api/hooks";
import { EARLIEST_DISCLAIMER } from "@/lib/copy";
import { explainDate } from "@/lib/explain";
import { formatUtc } from "@/lib/time";
import { buildWorkspace, step } from "@/lib/workspace";
import { searchProblem } from "@/lib/search-problem";

const VIEWS = ["timeline", "lineage", "evidence"] as const;
type View = (typeof VIEWS)[number];

/** Three linked views of one run, sharing a selection. Keys: j/k move, e opens evidence, g switches view. */
const VIEW_HINT: Record<(typeof VIEWS)[number], string> = {
  timeline: "When each copy appeared, grouped by the story its page tells.",
  lineage: "How the picture changed: each row is a variant, arrows show which edit came from which.",
  evidence: "Every verified copy with its match, its date and the evidence that decided it.",
};

export function RunWorkspace({ runId }: { runId: string }) {
  const run = useRun(runId);
  const sightings = useRunSightings(runId);
  const analysis = useRunAnalysis(runId);
  const asset = useAsset(run.data?.asset_id ?? "");
  const [view, setView] = useState<View>("timeline");
  const [selected, setSelected] = useState<string | null>(null);
  const [drawer, setDrawer] = useState(false);

  const model = useMemo(
    () => (sightings.data ? buildWorkspace(sightings.data, analysis.data) : null),
    [sightings.data, analysis.data],
  );
  const order = useMemo(() => (model ? model.sightings.map((s) => s.id) : []), [model]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (target && ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName)) return;
      if (event.key === "j" || event.key === "k") {
        setSelected((current) => step(order, current, event.key === "j" ? 1 : -1));
      } else if (event.key === "e") {
        setDrawer(true);
      } else if (event.key === "g") {
        setView((v) => VIEWS[(VIEWS.indexOf(v) + 1) % VIEWS.length]);
      } else if (event.key === "Escape") {
        setDrawer(false);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [order]);

  if (run.isPending || sightings.isPending) return <p className="px-4 py-6 text-muted">Loading…</p>;
  if (run.error || sightings.error || !model || !run.data) {
    return <p className="px-4 py-6">{(run.error ?? sightings.error)?.message ?? "Run not found."}</p>;
  }

  const select = (id: string) => {
    setSelected(id);
    setDrawer(true);
  };
  const current = model.sightings.find((s) => s.id === selected) ?? null;
  const claim = analysis.data?.claims.find((c) => c.sighting_id === selected);
  const notes = { ...sightings.data.notes, ...(analysis.data?.notes ?? {}) };
  const problem = searchProblem(sightings.data.notes, sightings.data.candidates);

  const earliest = model.sightings.find((s) => s.id === model.earliestId) ?? null;
  const variants = analysis.data?.variants.length ?? 0;
  const narratives = analysis.data?.narratives.length ?? 0;
  const branches = analysis.data?.narratives.filter((n) => n.parent_narrative_id !== null).length ?? 0;
  const forwards = analysis.data?.propagation.length ?? 0;

  return (
    <div className="mx-auto flex w-full max-w-7xl flex-col gap-3 px-4 py-4">
      <nav className="flex flex-wrap items-center justify-between gap-2 text-[13px] text-muted">
        <span className="flex items-center gap-2">
          <Link href="/" className="hover:text-text">
            Cases
          </Link>
          <span className="text-faint">/</span>
          <Link href={`/assets/${run.data.asset_id}`} className="hover:text-text">
            Image
          </Link>
          <span className="text-faint">/</span>
          <span className="mono text-text">run {runId.slice(0, 8)}</span>
          <span className="label border border-line px-1.5 py-0.5">{run.data.status}</span>
        </span>
        <span className="flex gap-4">
          <Link href={`/runs/${runId}/brief`} className="hover:text-text">
            Brief (PDF)
          </Link>
          {SNAPSHOT ? null : (
            <a href={`${API_URL}/runs/${runId}/evidence-pack?download=true`} className="hover:text-text">
              Evidence pack (JSON)
            </a>
          )}
        </span>
      </nav>

      <section className="grid gap-px border border-line bg-line md:grid-cols-[auto_minmax(0,1fr)_minmax(0,1fr)]" aria-label="Summary">
        <div className="bg-surface-1 p-3">
          {asset.data ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={`${API_URL}${asset.data.display_url}`} alt="Query image" className="h-24 w-32 border border-line object-cover" />
          ) : null}
        </div>
        <div className="bg-surface-1 p-3">
          <p className="label">
            <Term name="earliest">Earliest found</Term>
          </p>
          {earliest ? (
            <>
              <p className="mt-1 text-[16px] font-semibold text-accent">
                {earliest.date_upper ? formatUtc(earliest.date_upper, "day") : "undated"}
                <span className="ml-2 font-normal text-text">{earliest.domain}</span>
              </p>
              <p className="mt-1 text-[13px] text-muted">{explainDate(earliest)}</p>
            </>
          ) : (
            <p className="mt-1 text-muted">No verified copy.</p>
          )}
          <p className="mt-2 border-l-2 border-accent pl-2 text-[12px] text-muted">{EARLIEST_DISCLAIMER}</p>
        </div>
        <dl className="grid grid-cols-2 content-start gap-px bg-line [&>div:last-child:nth-child(odd)]:col-span-2">
          {[
            { k: "sighting" as const, label: "Verified copies", value: model.sightings.length },
            { k: "variant" as const, label: "Variants", value: variants },
            { k: "narrative" as const, label: "Stories", value: narratives },
            { k: "divergence" as const, label: "Story changes", value: branches },
            ...(forwards ? [{ k: "forward" as const, label: "Forwards", value: forwards }] : []),
          ].map((stat) => (
            <div key={stat.label} className="bg-surface-1 px-3 py-2">
              <dt className="label">
                <Term name={stat.k}>{stat.label}</Term>
              </dt>
              <dd className="mono mt-0.5 text-[20px]">{stat.value}</dd>
            </div>
          ))}
        </dl>
      </section>

      {problem ? (
        <p role="alert" className="border border-line border-l-2 border-l-conf-low bg-surface-1 px-3 py-2 text-[13px] font-semibold">
          {problem}
        </p>
      ) : null}

      <details className="border border-line bg-surface-1 text-[13px]">
        <summary className="label cursor-pointer px-3 py-2 hover:text-text">How to read this investigation</summary>
        <div className="grid gap-x-6 gap-y-2 border-t border-line px-3 py-3 text-muted md:grid-cols-2">
          <p>
            A <Term name="sighting" /> is a copy ORIGIN fetched and proved to be your picture. Each is an{" "}
            <Term name="exact">identical file</Term>, the <Term name="near_duplicate">same picture</Term> or an{" "}
            <Term name="derivative">edited copy</Term>.
          </p>
          <p>
            Dates are <Term name="interval">ranges</Term>: the copy was online by the later date and could not have
            appeared before the earlier one. Colour shows <Term name="confidence" />; amber marks the earliest found.
          </p>
          <p>
            <Term name="variant">Variants</Term> group copies that look alike. The lineage view shows which edit was
            made from which, and Telegram <Term name="forward">forwards</Term> when they exist.
          </p>
          <p>
            Pages that say what the picture shows are read for claims and grouped into{" "}
            <Term name="narrative">stories</Term>. A contradicting story is a branch, starting at its{" "}
            <Term name="divergence">divergence point</Term>. Sources and copies carry Admiralty grades (
            <Term name="reliability" />, <Term name="credibility" />
            ).
          </p>
          <p className="md:col-span-2">
            Keys: <span className="mono text-text">j</span>/<span className="mono text-text">k</span> move through
            copies, <span className="mono text-text">e</span> opens the evidence,{" "}
            <span className="mono text-text">g</span> switches view.
          </p>
        </div>
      </details>

      <div role="tablist" aria-label="Views" className="flex gap-px border-b border-line">
        {VIEWS.map((v) => (
          <button
            key={v}
            role="tab"
            type="button"
            aria-selected={view === v}
            onClick={() => setView(v)}
            className={`-mb-px px-4 py-2 text-[13px] capitalize ${view === v ? "border-b-2 border-intent text-text" : "text-muted hover:text-text"}`}
          >
            {v}
          </button>
        ))}
      </div>

      <div className={`grid gap-3 ${drawer && current ? "lg:grid-cols-[minmax(0,1fr)_400px]" : ""}`}>
        <div className="flex min-w-0 flex-col gap-3">
          <Panel title={view} hint={view === "evidence" ? VIEW_HINT[view] : undefined}>
            {view === "timeline" ? <Timeline model={model} selected={selected} onSelect={select} /> : null}
            {view === "lineage" && analysis.data ? (
              <LineageGraph model={model} analysis={analysis.data} selected={selected} onSelect={select} />
            ) : null}
            {view === "lineage" && !analysis.data ? <p className="px-3 py-2 text-muted">No variant analysis for this run.</p> : null}
            {view === "evidence" ? <EvidenceTable model={model} selected={selected} onSelect={select} /> : null}
          </Panel>
          {Object.keys(notes).length ? (
            <Panel title="Run notes" hint="What ORIGIN could not do, or chose not to, in this run.">
              <ul className="divide-y divide-line text-[13px]">
                {Object.entries(notes).map(([k, v]) => (
                  <li key={k} className="grid grid-cols-[9rem_1fr] gap-3 px-3 py-1.5">
                    <span className="mono text-muted">{k}</span>
                    <span className="text-muted">{v}</span>
                  </li>
                ))}
              </ul>
            </Panel>
          ) : null}
        </div>
        {drawer && current && asset.data ? (
          <EvidenceDrawer
            runId={runId}
            assetDisplayUrl={asset.data.display_url}
            sighting={current}
            claim={claim}
            earliest={current.id === model.earliestId}
            onClose={() => setDrawer(false)}
          />
        ) : null}
      </div>
    </div>
  );
}
