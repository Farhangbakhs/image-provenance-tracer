import { Suspense } from "react";

import { CaseView } from "@/components/CaseView";
import { snapshotParams } from "@/lib/snapshot-params";

export function generateStaticParams() {
  return snapshotParams("cases");
}

export default function CasePage({ params }: PageProps<"/cases/[id]">) {
  return (
    <Suspense fallback={<p className="px-4 py-6 text-muted">Loading…</p>}>
      {params.then(({ id }) => (
        <CaseView caseId={id} />
      ))}
    </Suspense>
  );
}
