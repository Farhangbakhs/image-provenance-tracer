"use client";

import Link from "next/link";

import { DISCLOSURE } from "@/components/Intake";
import { DropZone } from "@/components/DropZone";
import { Panel } from "@/components/Panel";
import { API_URL } from "@/lib/api/client";
import { useCase, useUploadToCase } from "@/lib/api/hooks";
import { formatUtc } from "@/lib/time";

const CREDENTIAL_LABELS = {
  none: "no credentials",
  present_untrusted: "credentials, untrusted",
  valid_trusted: "credentials, trusted",
} as const;

export function CaseView({ caseId }: { caseId: string }) {
  const { data, error, isPending } = useCase(caseId);
  const upload = useUploadToCase(caseId);

  if (isPending) return <p className="px-4 py-6 text-muted">Loading…</p>;
  if (error || !data) return <p className="px-4 py-6">{error?.message ?? "Case not found."}</p>;

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-4 px-4 py-6">
      <nav className="text-[12px] text-muted">
        <Link href="/" className="hover:text-text">
          ← All cases
        </Link>
      </nav>
      <header>
        <h1 className="text-[15px] font-semibold">{data.title}</h1>
        <p className="mono text-[11px] text-muted">opened {formatUtc(data.created_at)}</p>
        {data.notes ? <p className="mt-2 max-w-prose text-muted">{data.notes}</p> : null}
      </header>
      <Panel title="Images" aside={`${data.assets.length}`}>
        {data.assets.length === 0 ? <p className="px-3 py-2 text-muted">No images yet.</p> : null}
        <ul className="grid grid-cols-2 gap-px bg-line sm:grid-cols-4">
          {data.assets.map((a) => (
            <li key={a.id} className="bg-surface-1">
              <Link href={`/assets/${a.id}`} className="block hover:bg-surface-2">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={`${API_URL}/assets/${a.id}/display`}
                  alt={a.original_filename ?? "uploaded image"}
                  loading="lazy"
                  className="aspect-[4/3] w-full object-cover"
                />
                <div className="px-2 py-1.5">
                  <div className="truncate text-[12px]">{a.original_filename ?? a.id}</div>
                  <div className="mono text-[11px] text-muted">
                    {a.width}×{a.height} · {CREDENTIAL_LABELS[a.c2pa_state]}
                  </div>
                </div>
              </Link>
            </li>
          ))}
        </ul>
      </Panel>
      <Panel title="Add an image">
        <div className="flex flex-col gap-3 p-3">
          <DropZone onFile={(file) => upload.mutate(file)} busy={upload.isPending} />
          {upload.error ? (
            <p role="alert" className="border border-line px-3 py-2 text-[12px]">
              {upload.error.message}
            </p>
          ) : null}
          <p className="text-[11px] text-muted">{DISCLOSURE}</p>
        </div>
      </Panel>
    </div>
  );
}
