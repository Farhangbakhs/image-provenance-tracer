import { Suspense } from "react";

import { Brief } from "@/components/Brief";
import { snapshotParams } from "@/lib/snapshot-params";

export function generateStaticParams() {
  return snapshotParams("runs");
}

export default function BriefPage({ params }: PageProps<"/runs/[id]/brief">) {
  return (
    <Suspense fallback={<p className="px-4 py-6 text-muted">Loading…</p>}>
      {params.then(({ id }) => (
        <Brief runId={id} />
      ))}
    </Suspense>
  );
}
