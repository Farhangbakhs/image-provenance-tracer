"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { Panel } from "@/components/Panel";
import { Term } from "@/components/ui/Term";
import { AnswerSummary } from "@/components/workspace/AnswerSummary";
import { CandidatesPanel } from "@/components/workspace/CandidatesPanel";
import { EvidenceDrawer, EvidenceTable } from "@/components/workspace/Evidence";
import { InvestigationGraph } from "@/components/workspace/InvestigationGraph";
import { RunDetails } from "@/components/workspace/RunDetails";
import { API_URL } from "@/lib/api/client";
import { useAsset, useRun, useRunAnalysis, useRunSightings } from "@/lib/api/hooks";
import { searchProblem } from "@/lib/search-problem";
import { buildSummary } from "@/lib/summary";
import { buildWorkspace, step } from "@/lib/workspace";

const VIEWS = ["graph", "list"] as const;
type View = (typeof VIEWS)[number];

/**
 * One investigation: the answer first, then the copies as a graph over time or as a list, sharing
 * one selection and one evidence panel. Keys: j/k move, e opens evidence, g switches view.
 */
export function RunWorkspace({ runId }: { runId: string }) {
  const run = useRun(runId);
  const sightings = useRunSightings(runId);
  const analysis = useRunAnalysis(runId);
  const asset = useAsset(run.data?.asset_id ?? "");
  const [view, setView] = useState<View>("graph");
  // Until the reader picks something, the earliest copy is selected and its evidence is open:
  // the page answers the question with zero clicks.
  const [picked, setPicked] = useState<string | null | undefined>(undefined);
  const [drawerOpen, setDrawerOpen] = useState<boolean | undefined>(undefined);
  const [details, setDetails] = useState(false);

  const model = useMemo(
    () => (sightings.data ? buildWorkspace(sightings.data, analysis.data) : null),
    [sightings.data, analysis.data],
  );
  const order = useMemo(() => (model ? model.sightings.map((s) => s.id) : []), [model]);
  const earliestId = model?.earliestId ?? null;

  const selected = picked === undefined ? earliestId : picked;
  const drawer = drawerOpen ?? true;

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (target && ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName)) return;
      if (event.key === "j" || event.key === "k") {
        setPicked((current) => step(order, current === undefined ? earliestId : current, event.key === "j" ? 1 : -1));
      } else if (event.key === "e") {
        setDrawerOpen(true);
      } else if (event.key === "g") {
        setView((v) => VIEWS[(VIEWS.indexOf(v) + 1) % VIEWS.length]);
      } else if (event.key === "Escape") {
        setDrawerOpen(false);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [order, earliestId]);

  if (run.isPending || sightings.isPending) return <p className="px-4 py-6 text-muted">Loading…</p>;
  if (run.error || sightings.error || !model || !run.data) {
    return <p className="px-4 py-6">{(run.error ?? sightings.error)?.message ?? "Run not found."}</p>;
  }

  const select = (id: string) => {
    setPicked(id);
    setDetails(false);
    setDrawerOpen(true);
  };
  const current = model.sightings.find((s) => s.id === selected) ?? null;
  const claim = analysis.data?.claims.find((c) => c.sighting_id === selected);
  const notes = { ...sightings.data.notes, ...(analysis.data?.notes ?? {}) };
  const problem = searchProblem(sightings.data.notes, sightings.data.candidates);
  const summary = buildSummary(model, analysis.data, sightings.data.candidates);

  return (
    <div className="mx-auto flex w-full max-w-7xl flex-col gap-4 px-4 py-4">
      <nav className="flex flex-wrap items-center justify-between gap-2 text-[13px] text-muted" aria-label="Breadcrumb">
        <span className="flex items-center gap-2">
          <Link href="/" className="hover:text-text">
            Cases
          </Link>
          <span className="text-faint">/</span>
          <Link href={`/assets/${run.data.asset_id}`} className="hover:text-text">
            Image
          </Link>
          <span className="text-faint">/</span>
          <span className="text-text">Investigation</span>
        </span>
        <span className="flex gap-4">
          <Link href={`/runs/${runId}/brief`} className="hover:text-text">
            Brief (PDF)
          </Link>
          <a href={`${API_URL}/runs/${runId}/evidence-pack?download=true`} className="hover:text-text">
            Evidence pack (JSON)
          </a>
        </span>
      </nav>

      <AnswerSummary
        summary={summary}
        imageUrl={asset.data ? `${API_URL}${asset.data.display_url}` : null}
        onSelect={select}
        onDetails={() => setDetails((d) => !d)}
      />

      {problem ? (
        <p role="alert" className="border border-line border-l-2 border-l-accent bg-surface-1 px-3 py-2 font-semibold">
          {problem}
        </p>
      ) : null}

      <details className="border border-line bg-surface-1 text-[13px]">
        <summary className="label cursor-pointer px-3 py-2 hover:text-text">How to read this</summary>
        <div className="grid gap-x-6 gap-y-2 border-t border-line px-3 py-3 text-muted md:grid-cols-2">
          <p>
            Every copy here was fetched by ORIGIN and proved to be your picture: an{" "}
            <Term name="exact">identical file</Term>, the <Term name="near_duplicate">same picture</Term> or an{" "}
            <Term name="derivative">edited copy</Term>. The graph places each one at the earliest date its evidence allows.
          </p>
          <p>
            <Term name="variant">Variants</Term> are copies that look alike; arrows show which edit was made from which.
            Switch the graph to <span className="text-text">What it claims</span> to group copies by the{" "}
            <Term name="narrative">story</Term> their page tells.
          </p>
          <p>
            Dates are <Term name="interval">ranges</Term> with a stated <Term name="confidence" />. The{" "}
            <Term name="earliest">earliest found</Term> is the earliest proven date, and earlier copies may exist.
          </p>
          <p>
            Click any copy for its evidence. Keys: <span className="mono text-text">j</span>/
            <span className="mono text-text">k</span> move, <span className="mono text-text">e</span> opens evidence,{" "}
            <span className="mono text-text">g</span> switches between graph and list.
          </p>
        </div>
      </details>

      <div className={`grid gap-4 ${details || (drawer && current) ? "lg:grid-cols-[minmax(0,1fr)_400px]" : ""}`}>
        <div className="flex min-w-0 flex-col gap-4">
          <section className="border border-line bg-surface-1" aria-label="Copies">
            <div role="tablist" aria-label="Views" className="flex border-b border-line bg-surface-2">
              {VIEWS.map((v) => (
                <button
                  key={v}
                  role="tab"
                  type="button"
                  aria-selected={view === v}
                  onClick={() => setView(v)}
                  className={`-mb-px px-4 py-2 text-[13px] capitalize ${view === v ? "border-b-2 border-accent text-text" : "text-muted hover:text-text"}`}
                >
                  {v}
                </button>
              ))}
            </div>
            {view === "graph" && analysis.data ? (
              <InvestigationGraph model={model} analysis={analysis.data} selected={selected} onSelect={select} />
            ) : null}
            {view === "graph" && !analysis.data ? <p className="px-3 py-2 text-muted">No analysis for this run yet.</p> : null}
            {view === "list" ? <EvidenceTable model={model} selected={selected} onSelect={select} /> : null}
          </section>
          {Object.keys(notes).length ? (
            <Panel title="Notes on this run" hint="What ORIGIN could not do, or chose not to.">
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
          <CandidatesPanel runId={runId} />
        </div>
        {details ? (
          <RunDetails runId={runId} counts={sightings.data.candidates} onClose={() => setDetails(false)} />
        ) : null}
        {!details && drawer && current && asset.data ? (
          <EvidenceDrawer
            runId={runId}
            assetDisplayUrl={asset.data.display_url}
            sighting={current}
            claim={claim}
            earliest={current.id === model.earliestId}
            onClose={() => setDrawerOpen(false)}
          />
        ) : null}
      </div>
    </div>
  );
}
