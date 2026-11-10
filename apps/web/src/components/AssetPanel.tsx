"use client";

import Link from "next/link";
import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { Fields, Panel } from "@/components/Panel";
import { StageStrip } from "@/components/StageStrip";
import { API_URL, type AssetOut } from "@/lib/api/client";
import { useAsset, useRunProgress, useStartRun } from "@/lib/api/hooks";
import { describeCredentials } from "@/lib/credentials";
import { formatUtc } from "@/lib/time";

const STAGE_ORDER = ["ingest", "discover", "verify", "date", "branch", "report"];

function bytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(2)} MB`;
}

function Credentials({ asset }: { asset: AssetOut }) {
  const c = asset.credentials;
  const verdict = describeCredentials(c);
  const rows = [
    { label: "State", value: <span className={verdict.tampered ? "font-semibold" : ""}>{verdict.label}</span> },
    { label: "Validation", value: c.validation_state, mono: true },
    { label: "Signer", value: [c.signer_common_name, c.signer_issuer].filter(Boolean).join(" · ") || null },
    { label: "Signed at", value: c.signed_at ? formatUtc(c.signed_at, "second") : null, mono: true },
    { label: "Generator", value: c.claim_generator },
    { label: "Actions", value: c.actions.length ? c.actions.join(", ") : null, mono: true },
    { label: "Failures", value: c.failures.length ? c.failures.join(", ") : null, mono: true },
    { label: "Trust list", value: c.trust_list, mono: true },
  ].filter((row) => row.label === "State" || row.label === "Trust list" || row.value);
  return (
    <Panel title="Content Credentials">
      <p className="border-b border-line px-3 py-2 text-[12px] text-muted">{verdict.meaning}</p>
      <Fields rows={rows} />
    </Panel>
  );
}

function Metadata({ asset }: { asset: AssetOut }) {
  const m = asset.metadata;
  if (m.status !== "ok" || !m.summary) {
    return (
      <Panel title="Embedded metadata" aside="unavailable">
        <p className="px-3 py-2 text-[12px] text-muted">
          Metadata could not be read, which is not the same as the file having none. {m.error}
        </p>
      </Panel>
    );
  }
  const s = m.summary;
  const capture = s.capture_time
    ? s.capture_time.utc
      ? `${formatUtc(s.capture_time.utc, "second")} (from ${s.capture_time.tag})`
      : `${s.capture_time.stated}, zone not stated (${s.capture_time.tag})`
    : null;
  const gps =
    s.gps_latitude != null && s.gps_longitude != null
      ? `${s.gps_latitude.toFixed(6)}, ${s.gps_longitude.toFixed(6)}`
      : null;
  return (
    <Panel title="Embedded metadata" aside={`${m.tag_count} tags · ${m.tool} ${m.tool_version}`}>
      <p className="border-b border-line px-3 py-2 text-[12px] text-muted">
        Claims written inside the file. Easy to forge and often stripped; never proof on their own.
      </p>
      <Fields
        rows={[
          { label: "Capture time", value: capture, mono: true },
          { label: "Camera", value: [s.camera_make, s.camera_model].filter(Boolean).join(" ") || null },
          { label: "Software", value: s.software },
          { label: "GPS", value: gps, mono: true },
          { label: "Credit", value: s.credit },
          { label: "Copyright", value: s.copyright },
          { label: "Groups", value: s.groups.length ? s.groups.join(", ") : null, mono: true },
        ]}
      />
    </Panel>
  );
}

function Trace({ asset }: { asset: AssetOut }) {
  const queryClient = useQueryClient();
  const start = useStartRun(asset.id);
  const latest = asset.runs[0];
  const [runId, setRunId] = useState<string | undefined>(
    latest && (latest.status === "queued" || latest.status === "running") ? latest.id : undefined,
  );
  const progress = useRunProgress(runId, () =>
    queryClient.invalidateQueries({ queryKey: ["asset", asset.id] }),
  );

  return (
    <Panel
      title="Trace"
      aside={latest ? `last run ${formatUtc(latest.created_at)} · ${latest.status}` : "not run yet"}
    >
      <div className="flex flex-wrap items-center justify-between gap-3 px-3 py-2">
        <p className="max-w-prose text-[12px] text-muted">
          A trace runs the pipeline on this image. The SSCD embedding is computed in the ingest stage;
          later stages appear as they are built.
        </p>
        <button
          type="button"
          onClick={() => start.mutate(undefined, { onSuccess: (run) => setRunId(run.id) })}
          disabled={start.isPending || progress?.status === "running" || progress?.status === "connecting"}
          className="border border-line px-3 py-1 text-[12px] hover:border-text disabled:cursor-not-allowed disabled:text-muted"
        >
          {progress?.status === "running" || progress?.status === "connecting" ? "Running…" : "Start trace"}
        </button>
      </div>
      {start.error ? <p className="px-3 pb-2 text-[12px]">{start.error.message}</p> : null}
      {runId ? <StageStrip order={STAGE_ORDER} progress={progress} /> : null}
      {progress?.error ? <p className="mono border-t border-line px-3 py-2 text-[11px]">{progress.error}</p> : null}
    </Panel>
  );
}

export function AssetPanel({ assetId }: { assetId: string }) {
  const { data: asset, error, isPending } = useAsset(assetId);

  if (isPending) return <p className="px-4 py-6 text-muted">Loading…</p>;
  if (error || !asset) return <p className="px-4 py-6">{error?.message ?? "Image not found."}</p>;

  const f = asset.fingerprints;
  return (
    <div className="mx-auto grid w-full max-w-6xl gap-4 px-4 py-6 lg:grid-cols-[minmax(0,5fr)_minmax(0,6fr)]">
      <div className="flex min-w-0 flex-col gap-4">
        <nav className="text-[12px] text-muted">
          <Link href={`/cases/${asset.case_id}`} className="hover:text-text">
            ← Case
          </Link>
        </nav>
        <figure className="border border-line bg-surface-1">
          {/* The display copy is re-encoded by the API; Next's optimiser would encode it again. */}
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={`${API_URL}${asset.display_url}`}
            alt={`Uploaded image ${asset.original_filename ?? asset.id}`}
            className="block h-auto max-h-[70vh] w-full object-contain"
          />
          <figcaption className="mono flex justify-between gap-2 border-t border-line px-3 py-1.5 text-[11px] text-muted">
            <span className="truncate">{asset.original_filename ?? "upload"}</span>
            <span>
              {asset.width}×{asset.height} · {bytes(asset.byte_size)} · {asset.content_type}
            </span>
          </figcaption>
        </figure>
        <Panel title="Fingerprints">
          <Fields
            rows={[
              { label: "SHA-256", value: f.sha256, mono: true },
              { label: "PDQ", value: `${f.pdq} (quality ${f.pdq_quality})`, mono: true },
              { label: "pHash", value: f.phash, mono: true },
              { label: "dHash", value: f.dhash, mono: true },
              {
                label: "SSCD",
                value: asset.embedding.status === "computed" ? asset.embedding.model : "pending: computed by the first trace",
                mono: true,
              },
              { label: "Uploaded", value: formatUtc(asset.created_at, "second"), mono: true },
            ]}
          />
        </Panel>
      </div>
      <div className="flex min-w-0 flex-col gap-4 lg:pt-8">
        <Trace asset={asset} />
        <Credentials asset={asset} />
        <Metadata asset={asset} />
      </div>
    </div>
  );
}
