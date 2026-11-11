"use client";

import Link from "next/link";
import type { ReactNode } from "react";

import { API_URL, SNAPSHOT, type EvidencePack, type SightingOut } from "@/lib/api/client";
import { useEvidencePack } from "@/lib/api/hooks";
import { EARLIEST_DISCLAIMER, SIGNAL_LABEL } from "@/lib/copy";
import { formatInterval, formatUtc } from "@/lib/time";

/** Sightings are cited as S1, S2… in the order the evidence dates them. */
export function sightingRefs(pack: EvidencePack): Record<string, string> {
  return Object.fromEntries(pack.sightings.sightings.map((s, i) => [s.id, `S${i + 1}`]));
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="flex flex-col gap-2 border-t border-line pt-3">
      <h2 className="text-[11px] font-semibold uppercase tracking-[0.12em] text-muted">{title}</h2>
      {children}
    </section>
  );
}

function where(s: SightingOut): string {
  return s.page_url ?? s.image_url;
}

/** A printable account of one run: what was found, how it is dated, and every artefact behind it. */
export function Brief({ runId }: { runId: string }) {
  const pack = useEvidencePack(runId);
  if (pack.isPending) return <p className="px-4 py-6 text-muted">Loading…</p>;
  if (pack.error) return <p className="px-4 py-6">{pack.error.message}</p>;
  return <BriefDocument pack={pack.data} />;
}

export function BriefDocument({ pack }: { pack: EvidencePack }) {
  const refs = sightingRefs(pack);
  const sightings = pack.sightings.sightings;
  const byId = Object.fromEntries(sightings.map((s) => [s.id, s]));
  const earliest = pack.sightings.earliest_sighting_id ? byId[pack.sightings.earliest_sighting_id] : undefined;
  const { analysis } = pack;
  const claimById = Object.fromEntries(analysis.claims.map((c) => [c.id, c]));
  const roots = analysis.narratives.filter((n) => !n.parent_narrative_id);
  const branches = analysis.narratives.filter((n) => n.parent_narrative_id);
  const variantLabel = Object.fromEntries(analysis.variants.map((v) => [v.id, v.label]));
  const notes = { ...pack.sightings.notes, ...analysis.notes };
  const counts = pack.sightings.candidates;
  const models = Array.from(new Set(analysis.claims.map((c) => `${c.llm_provider} ${c.llm_model} (${c.prompt_version})`)));
  const thresholds = Array.from(new Set(sightings.map((s) => s.threshold_version)));
  const datingRules = Array.from(new Set(sightings.map((s) => s.dating_rule_version).filter(Boolean)));

  return (
    <div className="paper flex-1">
      <article className="mx-auto flex w-full max-w-[52rem] flex-col gap-4 px-6 py-6 text-[12px]">
        <nav className="no-print flex flex-wrap items-center gap-2 text-[12px]">
          <Link href={`/runs/${pack.run.id}`} className="text-muted hover:text-text">
            ← Workspace
          </Link>
          <span className="flex-1" />
          <a
            // A snapshot serves the saved pack as a plain file; the API streams it as a download.
            href={
              SNAPSHOT
                ? `${API_URL}/runs/${pack.run.id}/evidence-pack.json`
                : `${API_URL}/runs/${pack.run.id}/evidence-pack?download=true`
            }
            download={SNAPSHOT ? `origin-run-${pack.run.id}.json` : undefined}
            className="border border-line px-2 py-1 hover:border-text"
          >
            Download evidence pack (JSON)
          </a>
          <button type="button" onClick={() => window.print()} className="border border-text bg-text px-2 py-1 text-bg">
            Print or save as PDF
          </button>
        </nav>

        <header className="flex gap-4">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={`${API_URL}/assets/${pack.asset.id}/display`}
            alt="Query image"
            className="h-24 w-32 border border-line object-cover"
          />
          <div className="flex flex-col gap-1">
            <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-muted">ORIGIN provenance brief</p>
            <h1 className="text-[18px] font-semibold leading-tight">{pack.case.title}</h1>
            <p className="mono text-[11px] text-muted">
              run {pack.run.id} · generated {formatUtc(pack.generated_at)} · all times UTC
            </p>
            <p className="mono text-[11px] text-muted">query SHA-256 {pack.asset.sha256}</p>
          </div>
        </header>

        <Section title="Summary">
          {earliest ? (
            <p>
              <span className="font-semibold text-accent">Earliest found:</span> {refs[earliest.id]} on{" "}
              <span className="mono">{earliest.domain}</span>, {formatInterval(earliest.date_lower, earliest.date_upper)} (
              {earliest.date_confidence} confidence
              {earliest.deciding ? `, from the ${SIGNAL_LABEL[earliest.deciding.kind] ?? earliest.deciding.kind}` : ""}).
            </p>
          ) : (
            <p>No sighting could be dated.</p>
          )}
          <p className="border-l-2 border-accent pl-2 font-medium">{pack.disclaimer || EARLIEST_DISCLAIMER}</p>
          <p className="text-muted">
            {sightings.length} verified sighting{sightings.length === 1 ? "" : "s"} from {counts.verified + counts.unrelated + counts.fetch_failed + counts.pending}{" "}
            candidates ({counts.unrelated} unrelated, {counts.fetch_failed} could not be fetched) · {analysis.variants.length} variant
            {analysis.variants.length === 1 ? "" : "s"} · {analysis.narratives.length} narrative{analysis.narratives.length === 1 ? "" : "s"}
            {branches.length ? `, ${branches.length} diverging` : ""}.
          </p>
          {pack.case.notes ? <p className="text-muted">Case notes: {pack.case.notes}</p> : null}
        </Section>

        {analysis.narratives.length ? (
          <Section title="Narratives">
            <ol className="flex flex-col gap-3">
              {[...roots, ...branches].map((n) => (
                <li key={n.id} className={`border-l-2 pl-3 ${n.parent_narrative_id ? "border-line" : "border-accent"}`}>
                  <p className="font-semibold">
                    {n.parent_narrative_id ? "Branch: " : "Earliest narrative: "}
                    {n.label}
                  </p>
                  {n.summary ? <p>{n.summary}</p> : null}
                  <p className="text-muted">
                    {n.parent_narrative_id ? "Diverges at " : "First seen at "}
                    {refs[n.divergence_sighting_id]}
                    {byId[n.divergence_sighting_id] ? ` (${byId[n.divergence_sighting_id].domain})` : ""}
                    {n.divergence_reason ? `: ${n.divergence_reason}` : ""}
                  </p>
                  <ul className="mt-1 flex flex-col gap-1">
                    {n.claim_ids.map((id) => {
                      const claim = claimById[id];
                      if (!claim) return null;
                      return (
                        <li key={id}>
                          <span className="mono text-muted">[{refs[claim.sighting_id]}]</span> “{claim.quote}”
                          {claim.translation ? <span className="text-muted"> ({claim.translation})</span> : null}
                          {claim.analyst_status === "overruled" ? <span className="text-conf-low"> · overruled by analyst</span> : null}
                        </li>
                      );
                    })}
                  </ul>
                </li>
              ))}
            </ol>
          </Section>
        ) : null}

        <Section title="Sightings">
          <table className="w-full border-collapse text-left text-[11px]">
            <thead className="text-muted">
              <tr className="border-b border-line">
                <th className="py-1 pr-2 font-medium">Ref</th>
                <th className="py-1 pr-2 font-medium">Dated</th>
                <th className="py-1 pr-2 font-medium">Where</th>
                <th className="py-1 pr-2 font-medium">Match</th>
                <th className="py-1 font-medium">Grade</th>
              </tr>
            </thead>
            <tbody>
              {sightings.map((s) => (
                <tr key={s.id} className="border-b border-line align-top">
                  <td className={`mono py-1 pr-2 ${s.id === earliest?.id ? "font-semibold text-accent" : ""}`}>{refs[s.id]}</td>
                  <td className="py-1 pr-2">
                    {formatInterval(s.date_lower, s.date_upper)}
                    <div className="text-muted">
                      {s.date_confidence}
                      {s.deciding ? ` · ${SIGNAL_LABEL[s.deciding.kind] ?? s.deciding.kind}` : ""}
                    </div>
                  </td>
                  <td className="mono break-all py-1 pr-2">{where(s)}</td>
                  <td className="py-1 pr-2">
                    {s.match_class.replace("_", "-")}
                    {s.variant_id && variantLabel[s.variant_id] ? ` · ${variantLabel[s.variant_id]}` : ""}
                    <div className="mono text-muted">
                      {s.sscd_cosine != null ? `SSCD ${s.sscd_cosine.toFixed(3)}` : ""}
                      {s.phash_distance != null ? ` · pHash ${s.phash_distance}` : ""}
                    </div>
                    {s.analyst_status === "overruled" ? <div className="text-conf-low">overruled by analyst</div> : null}
                  </td>
                  <td className="mono py-1">{s.reliability && s.credibility ? `${s.reliability}${s.credibility}` : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="text-muted">
            Grades use the Admiralty scale: the letter is the source&apos;s reliability (F: cannot be judged), the number the
            credibility of this sighting from its independent evidence.
          </p>
        </Section>

        {analysis.edges.length ? (
          <Section title="Variant edits">
            <ul className="flex flex-col gap-1">
              {analysis.edges.map((e) => (
                <li key={`${e.parent_variant_id}-${e.child_variant_id}`}>
                  <span className="mono">
                    {variantLabel[e.parent_variant_id]} → {variantLabel[e.child_variant_id]}
                  </span>{" "}
                  {e.kind}: {e.reason}
                </li>
              ))}
            </ul>
          </Section>
        ) : null}

        {Object.keys(notes).length ? (
          <Section title="Limits of this search">
            <ul className="flex flex-col gap-1 text-muted">
              {Object.entries(notes).map(([k, v]) => (
                <li key={k}>
                  <span className="mono">{k}</span>: {v}
                </li>
              ))}
            </ul>
          </Section>
        ) : null}

        <Section title="Method">
          <p className="text-muted">
            Providers: {pack.run.providers.join(", ") || "none"}. Match thresholds: {thresholds.join(", ") || "—"}. Dating
            rule: {datingRules.join(", ") || "—"}.{" "}
            {models.length ? `Claims read by ${models.join("; ")}; every quote is verbatim from the cited page.` : ""}
          </p>
        </Section>

        <Section title={`Artefacts (${pack.artefacts.length})`}>
          <table className="w-full border-collapse text-left text-[10px]">
            <thead className="text-muted">
              <tr className="border-b border-line">
                <th className="py-1 pr-2 font-medium">Kind</th>
                <th className="py-1 pr-2 font-medium">SHA-256</th>
                <th className="py-1 pr-2 font-medium">Fetched</th>
                <th className="py-1 font-medium">Source</th>
              </tr>
            </thead>
            <tbody>
              {pack.artefacts.map((a) => (
                <tr key={a.id} className="border-b border-line align-top">
                  <td className="py-1 pr-2">{a.kind.replaceAll("_", " ")}</td>
                  <td className="mono break-all py-1 pr-2">{a.sha256}</td>
                  <td className="mono whitespace-nowrap py-1 pr-2">{formatUtc(a.fetched_at, "second")}</td>
                  <td className="mono break-all py-1">{a.source_url ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Section>
      </article>
    </div>
  );
}
