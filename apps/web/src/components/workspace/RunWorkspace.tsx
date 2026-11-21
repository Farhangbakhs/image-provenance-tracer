"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { FoldPanel } from "@/components/Panel";
import { Term } from "@/components/ui/Term";
import { AnswerSummary } from "@/components/workspace/AnswerSummary";
import { CandidatesPanel } from "@/components/workspace/CandidatesPanel";
import { EvidenceDrawer, EvidenceTable } from "@/components/workspace/Evidence";
import { InvestigationGraph } from "@/components/workspace/InvestigationGraph";
import { RunDetails } from "@/components/workspace/RunDetails";
import { GroupPanel, StoryPanel } from "@/components/workspace/StoryPanel";
import { StoryTimeline } from "@/components/workspace/StoryTimeline";
import { API_URL } from "@/lib/api/client";
import { useAsset, useRun, useRunAnalysis, useRunSightings } from "@/lib/api/hooks";
import { searchProblem } from "@/lib/search-problem";
import { buildStories } from "@/lib/stories";
import { buildSummary } from "@/lib/summary";
import { placedTime } from "@/lib/timeline";
import { useTimelineView } from "@/lib/useTimelineView";
import { buildWorkspace, NO_CLAIM_LANE, step } from "@/lib/workspace";

const VIEWS = ["graph", "list"] as const;
type View = (typeof VIEWS)[number];
type Group = "story" | "variant";
type Side = "copy" | "story" | "details" | "group" | null;

/** One mark of the timeline, drawn as the timeline draws it, with what it means. */
function Key({ children, label }: { children: React.ReactNode; label: string }) {
  return (
    <span className="inline-flex items-center gap-1.5 whitespace-nowrap">
      <svg width={20} height={20} viewBox="-10 -10 20 20" aria-hidden>
        {children}
      </svg>
      <span>{label}</span>
    </span>
  );
}

/**
 * One investigation: the answer first, then the copies as stories on a timeline (or by how they
 * look) or as a list, sharing one selection and one side panel. Keys: j/k move, e opens the
 * evidence, g switches view, Esc closes the panel.
 */
export function RunWorkspace({ runId }: { runId: string }) {
  const run = useRun(runId);
  const sightings = useRunSightings(runId);
  const analysis = useRunAnalysis(runId);
  const asset = useAsset(run.data?.asset_id ?? "");
  const [view, setView] = useState<View>("graph");
  const [group, setGroup] = useState<Group>("story");
  // Until the reader picks something, the earliest copy is selected and its evidence is open:
  // the page answers the question with zero clicks.
  const [picked, setPicked] = useState<string | null | undefined>(undefined);
  const [sideChoice, setSide] = useState<Side | undefined>(undefined);
  const [storyId, setStoryId] = useState<string | null>(null);
  const [groupIds, setGroupIds] = useState<string[]>([]);

  const model = useMemo(
    () => (sightings.data ? buildWorkspace(sightings.data, analysis.data) : null),
    [sightings.data, analysis.data],
  );
  const order = useMemo(() => (model ? model.sightings.map((s) => s.id) : []), [model]);
  const earliestId = model?.earliestId ?? null;

  // The timeline's window. It opens on the densest period holding the earliest copy and the
  // original story's first copy, and "Reset view" returns to it.
  const times = useMemo(
    () => (model ? model.sightings.map(placedTime).filter((t): t is number => t !== null) : []),
    [model],
  );
  const anchors = useMemo(() => {
    if (!model) return [];
    const earliest = model.sightings.find((s) => s.id === model.earliestId);
    const root = buildStories(model, analysis.data, true).rows.find((r) => r.root)?.first;
    return [earliest, root].map((s) => (s ? placedTime(s) : null)).filter((t): t is number => t !== null);
  }, [model, analysis.data]);
  const timeline = useTimelineView(times, anchors);

  const selected = picked === undefined ? earliestId : picked;
  const side = sideChoice === undefined ? "copy" : sideChoice;

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (target && ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName)) return;
      if (event.key === "j" || event.key === "k") {
        setPicked((current) => step(order, current === undefined ? earliestId : current, event.key === "j" ? 1 : -1));
        setSide("copy");
      } else if (event.key === "e") {
        setSide("copy");
      } else if (event.key === "g") {
        setView((v) => VIEWS[(VIEWS.indexOf(v) + 1) % VIEWS.length]);
      } else if (event.key === "Escape") {
        setSide(null);
        setStoryId(null);
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
    setSide("copy");
    const lane = model.laneOf[id];
    setStoryId(lane && lane !== NO_CLAIM_LANE ? lane : null);
  };
  const selectStory = (id: string) => {
    setStoryId(id);
    setSide("story");
  };
  const selectGroup = (ids: string[]) => {
    setGroupIds(ids);
    setSide("group");
  };
  const current = model.sightings.find((s) => s.id === selected) ?? null;
  const claim = analysis.data?.claims.find((c) => c.sighting_id === selected);
  const notes = { ...sightings.data.notes, ...(analysis.data?.notes ?? {}) };
  const problem = searchProblem(sightings.data.notes, sightings.data.candidates);
  const summary = buildSummary(model, analysis.data, sightings.data.candidates);
  const storyRow = storyId ? buildStories(model, analysis.data, true).rows.find((r) => r.id === storyId) ?? null : null;
  const groupCopies = groupIds.map((id) => model.sightings.find((s) => s.id === id)).filter((s) => s !== undefined);
  const sideOpen =
    side === "details" ||
    (side === "group" && groupCopies.length > 0) ||
    (side === "story" && storyRow !== null) ||
    (side === "copy" && current !== null);

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
        onDetails={() => setSide(side === "details" ? "copy" : "details")}
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
            <Term name="derivative">edited copy</Term>. Each one is drawn at the earliest date its evidence allows.
          </p>
          <p>
            Each row is a <Term name="narrative">story</Term> a page tells about the picture, the original first; click its name
            for the story and its copies. Switch to{" "}
            <span className="text-text">How it looks</span> to see the <Term name="variant">variants</Term> and which edit was
            made from which.
          </p>
          <p>
            Dates are <Term name="interval">ranges</Term> with a stated <Term name="confidence" />. The{" "}
            <Term name="earliest">earliest found</Term> is the earliest proven date, and earlier copies may exist.
          </p>
          <p>
            Zoom the timeline with <span className="mono text-text">Ctrl</span> + scroll or a pinch, drag empty space to pan, or
            drag the overview strip above it. Click a numbered bundle to zoom into its copies, and use{" "}
            <span className="text-text">Reset view</span> to come back. Plain scrolling still scrolls the page.
          </p>
          <p className="flex flex-wrap items-center gap-x-5 gap-y-1 md:col-span-2" aria-label="Key to the timeline marks">
            <Key label="copy, date within a year">
              <circle r={4} fill="var(--muted)" />
            </Key>
            <Key label="copy, date uncertain">
              <circle r={4} fill="none" stroke="var(--muted)" strokeWidth={1.5} />
            </Key>
            <Key label="first copy of a story">
              <circle r={7} fill="none" stroke="var(--muted)" />
              <circle r={4} fill="var(--muted)" />
            </Key>
            <Key label="copies too close to tell apart">
              <circle r={9} fill="var(--surface-2)" stroke="var(--muted)" />
              <text y={4} textAnchor="middle" fontSize={11} fill="var(--text)">
                3
              </text>
            </Key>
            <Key label="original story, or what you selected">
              <circle r={4} fill="var(--accent)" />
            </Key>
          </p>
          <p>
            Click any copy for its evidence. Keys: <span className="mono text-text">+</span> / <span className="mono text-text">−</span>{" "}
            zoom, <span className="mono text-text">←</span> / <span className="mono text-text">→</span> pan,{" "}
            <span className="mono text-text">0</span> resets, <span className="mono text-text">Tab</span> and the arrows move
            between dots, <span className="mono text-text">Enter</span> pins one, <span className="mono text-text">Esc</span>{" "}
            clears; <span className="mono text-text">j</span>/<span className="mono text-text">k</span> step through copies,{" "}
            <span className="mono text-text">e</span> opens evidence, <span className="mono text-text">g</span> switches between
            graph and list.
          </p>
        </div>
      </details>

      <div className={`grid gap-4 ${sideOpen ? "lg:grid-cols-[minmax(0,1fr)_400px]" : ""}`}>
        <div className="flex min-w-0 flex-col gap-4">
          <section className="border border-line bg-surface-1" aria-label="Copies">
            <div className="flex flex-wrap items-center justify-between border-b border-line bg-surface-2">
              <div role="tablist" aria-label="Views" className="flex">
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
              {view === "graph" ? (
                <div role="radiogroup" aria-label="Group copies by" className="flex items-center gap-2 px-3 text-[12px]">
                  {group === "story" ? (
                    <button
                      type="button"
                      onClick={timeline.reset}
                      disabled={timeline.isDefault}
                      className="mr-2 border border-line px-2 py-1 text-muted hover:border-text hover:text-text disabled:opacity-40 disabled:hover:border-line disabled:hover:text-muted"
                    >
                      Reset view
                    </button>
                  ) : null}
                  <span className="label">Group by</span>
                  {(
                    [
                      ["story", "What it claims"],
                      ["variant", "How it looks"],
                    ] as const
                  ).map(([value, label]) => (
                    <button
                      key={value}
                      type="button"
                      role="radio"
                      aria-checked={group === value}
                      onClick={() => setGroup(value)}
                      className={`border px-2 py-1 ${group === value ? "border-accent bg-accent-soft text-text" : "border-line text-muted hover:text-text"}`}
                    >
                      {label}
                    </button>
                  ))}
                </div>
              ) : null}
            </div>
            {view === "graph" && group === "story" ? (
              <StoryTimeline
                model={model}
                analysis={analysis.data}
                selected={selected}
                selectedStory={storyId}
                timeline={timeline}
                onSelect={select}
                onSelectStory={selectStory}
                onSelectGroup={selectGroup}
              />
            ) : null}
            {view === "graph" && group === "variant" && analysis.data ? (
              <InvestigationGraph model={model} analysis={analysis.data} selected={selected} onSelect={select} />
            ) : null}
            {view === "graph" && group === "variant" && !analysis.data ? (
              <p className="px-3 py-2 text-muted">No analysis for this run yet.</p>
            ) : null}
            {view === "list" ? <EvidenceTable model={model} selected={selected} onSelect={select} /> : null}
          </section>
          {Object.keys(notes).length ? (
            <FoldPanel title="Notes on this run" note={`${Object.keys(notes).length} ${Object.keys(notes).length === 1 ? "note" : "notes"}: what ORIGIN could not do, or chose not to`}>
              <ul className="divide-y divide-line text-[13px]">
                {Object.entries(notes).map(([k, v]) => (
                  <li key={k} className="grid grid-cols-[9rem_1fr] gap-3 px-3 py-1.5">
                    <span className="mono text-muted">{k}</span>
                    <span className="text-muted">{v}</span>
                  </li>
                ))}
              </ul>
            </FoldPanel>
          ) : null}
          <CandidatesPanel runId={runId} />
        </div>
        {side === "details" ? (
          <RunDetails runId={runId} counts={sightings.data.candidates} onClose={() => setSide(null)} />
        ) : null}
        {side === "group" && groupCopies.length > 0 ? (
          <GroupPanel copies={groupCopies} selected={selected} onSelect={select} onClose={() => setSide(null)} />
        ) : null}
        {side === "story" && storyRow ? (
          <StoryPanel row={storyRow} selected={selected} onSelect={select} onClose={() => setSide(null)} />
        ) : null}
        {side === "copy" && current && asset.data ? (
          <EvidenceDrawer
            runId={runId}
            assetDisplayUrl={asset.data.display_url}
            sighting={current}
            claim={claim}
            earliest={current.id === model.earliestId}
            onClose={() => setSide(null)}
          />
        ) : null}
      </div>
    </div>
  );
}
