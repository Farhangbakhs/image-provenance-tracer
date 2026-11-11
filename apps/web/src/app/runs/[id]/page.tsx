import { Suspense } from "react";

import { RunWorkspace } from "@/components/workspace/RunWorkspace";
import { snapshotParams } from "@/lib/snapshot-params";

export function generateStaticParams() {
  return snapshotParams("runs");
}

export default function RunPage({ params }: PageProps<"/runs/[id]">) {
  return (
    <Suspense fallback={<p className="px-4 py-6 text-muted">Loading…</p>}>
      {params.then(({ id }) => (
        <RunWorkspace runId={id} />
      ))}
    </Suspense>
  );
}
