import { Suspense } from "react";

import { AssetPanel } from "@/components/AssetPanel";

export default function AssetPage({ params }: PageProps<"/assets/[id]">) {
  return (
    <Suspense fallback={<p className="px-4 py-6 text-muted">Loading…</p>}>
      {params.then(({ id }) => (
        <AssetPanel assetId={id} />
      ))}
    </Suspense>
  );
}
