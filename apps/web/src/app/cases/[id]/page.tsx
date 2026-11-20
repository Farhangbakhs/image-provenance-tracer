import { Suspense } from "react";

import { CaseView } from "@/components/CaseView";

export default function CasePage({ params }: PageProps<"/cases/[id]">) {
  return (
    <Suspense fallback={<p className="px-4 py-6 text-muted">Loading…</p>}>
      {params.then(({ id }) => (
        <CaseView caseId={id} />
      ))}
    </Suspense>
  );
}
