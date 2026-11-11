"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { DropZone } from "@/components/DropZone";
import { Panel } from "@/components/Panel";
import { SNAPSHOT } from "@/lib/api/client";
import { ApiError, createCase, uploadAsset, useCases } from "@/lib/api/hooks";
import { formatUtc } from "@/lib/time";

/** Who receives the image. Kept beside the drop zone so it is read before anything is sent. */
export const DISCLOSURE =
  "Uploading stores the image on this ORIGIN server only. No third party receives it at this step. " +
  "Reverse-image providers are listed here, with what each one receives, before a trace sends anything to them.";

export function Intake() {
  const router = useRouter();
  const [title, setTitle] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();

  const onFile = async (file: File) => {
    setBusy(true);
    setError(undefined);
    try {
      const created = await createCase(title.trim() || file.name);
      const asset = await uploadAsset(created.id, file);
      router.push(`/assets/${asset.id}`);
    } catch (err) {
      setError(err instanceof ApiError || err instanceof Error ? err.message : String(err));
      setBusy(false);
    }
  };

  return (
    <Panel title="New case">
      <div className="flex flex-col gap-3 p-3">
        <label className="flex flex-col gap-1">
          <span className="text-[11px] text-muted">Case title (optional; defaults to the file name)</span>
          <input
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            maxLength={200}
            placeholder="e.g. Flooded street, claimed Valencia"
            className="border border-line bg-bg px-2 py-1.5 text-[13px] outline-none placeholder:text-muted focus:border-text"
          />
        </label>
        <DropZone onFile={onFile} busy={busy} busyLabel="Uploading and fingerprinting…" />
        {error ? (
          <p role="alert" className="border border-line px-3 py-2 text-[12px]">
            {error}
          </p>
        ) : null}
        <p className="text-[11px] text-muted">{DISCLOSURE}</p>
      </div>
    </Panel>
  );
}

export function RecentCases() {
  const { data, isPending, error } = useCases();
  return (
    <Panel title={SNAPSHOT ? "Demo investigations" : "Recent cases"}>
      {isPending ? <p className="px-3 py-2 text-muted">Loading…</p> : null}
      {error ? <p className="px-3 py-2 text-[12px]">{error.message}</p> : null}
      {data && data.length === 0 ? <p className="px-3 py-2 text-muted">No cases yet.</p> : null}
      {data && data.length > 0 ? (
        <ul className="divide-y divide-line">
          {data.map((c) => (
            <li key={c.id}>
              <Link href={`/cases/${c.id}`} className="block px-3 py-2 hover:bg-surface-2">
                <span className="flex justify-between gap-3">
                  <span className="truncate font-medium">{c.title}</span>
                  <span className="mono shrink-0 text-[12px] text-faint">{formatUtc(c.created_at, "day")}</span>
                </span>
                {c.notes ? <span className="mt-0.5 line-clamp-2 block text-[13px] text-muted">{c.notes}</span> : null}
              </Link>
            </li>
          ))}
        </ul>
      ) : null}
    </Panel>
  );
}
