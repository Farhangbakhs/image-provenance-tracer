"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { Panel } from "@/components/Panel";
import { EvidenceDrawer, EvidenceTable } from "@/components/workspace/Evidence";
import { Timeline } from "@/components/workspace/Timeline";
import { VariantGraph } from "@/components/workspace/VariantGraph";
import { API_URL } from "@/lib/api/client";
import { useAsset, useRun, useRunAnalysis, useRunSightings } from "@/lib/api/hooks";
import { EARLIEST_DISCLAIMER } from "@/lib/copy";
import { buildWorkspace, step } from "@/lib/workspace";

const VIEWS = ["timeline", "graph", "evidence"] as const;
type View = (typeof VIEWS)[number];

/** Three linked views of one run, sharing a selection. Keys: j/k move, e opens evidence, g switches view. */
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

  return (
    <div className="mx-auto flex w-full max-w-7xl flex-col gap-3 px-4 py-4">
      <nav className="flex items-center justify-between text-[12px] text-muted">
        <Link href={`/assets/${run.data.asset_id}`} className="hover:text-text">
          ← Image
        </Link>
        <span className="mono">
          run {runId.slice(0, 8)} · {run.data.status} · j/k move · e evidence · g switch view
        </span>
        <span className="flex gap-3">
          <Link href={`/runs/${runId}/brief`} className="hover:text-text">
            Brief (PDF)
          </Link>
          <a href={`${API_URL}/runs/${runId}/evidence-pack?download=true`} className="hover:text-text">
            Evidence pack (JSON)
          </a>
        </span>
      </nav>
      <div className="flex items-center gap-3">
        {asset.data ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={`${API_URL}${asset.data.display_url}`} alt="Query image" className="h-14 w-20 border border-line object-cover" />
        ) : null}
        <div>
          <h1 className="text-[15px] font-semibold">
            {model.sightings.length} verified sighting{model.sightings.length === 1 ? "" : "s"}
            {analysis.data ? ` · ${analysis.data.variants.length} variants · ${analysis.data.narratives.length} narratives` : ""}
          </h1>
          <p className="border-l border-accent pl-2 text-[12px] text-muted">{EARLIEST_DISCLAIMER}</p>
        </div>
      </div>

      <div role="tablist" aria-label="Views" className="flex gap-px border-b border-line">
        {VIEWS.map((v) => (
          <button
            key={v}
            role="tab"
            type="button"
            aria-selected={view === v}
            onClick={() => setView(v)}
            className={`px-3 py-1.5 text-[12px] capitalize ${view === v ? "border-b border-text text-text" : "text-muted hover:text-text"}`}
          >
            {v}
          </button>
        ))}
      </div>

      <div className={`grid gap-0 ${drawer && current ? "lg:grid-cols-[minmax(0,1fr)_380px]" : ""}`}>
        <Panel title={view} aside={Object.keys(notes).length ? `${Object.keys(notes).length} note(s)` : undefined}>
          {view === "timeline" ? <Timeline model={model} selected={selected} onSelect={select} /> : null}
          {view === "graph" && analysis.data ? (
            <VariantGraph model={model} analysis={analysis.data} selected={selected} onSelect={select} />
          ) : null}
          {view === "graph" && !analysis.data ? <p className="px-3 py-2 text-muted">No variant analysis for this run.</p> : null}
          {view === "evidence" ? <EvidenceTable model={model} selected={selected} onSelect={select} /> : null}
          {Object.keys(notes).length ? (
            <ul className="border-t border-line px-3 py-2 text-[11px] text-muted">
              {Object.entries(notes).map(([k, v]) => (
                <li key={k}>
                  <span className="mono">{k}</span>: {v}
                </li>
              ))}
            </ul>
          ) : null}
        </Panel>
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
