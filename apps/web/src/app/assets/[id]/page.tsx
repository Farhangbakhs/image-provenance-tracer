import { Suspense } from "react";

import { AssetPanel } from "@/components/AssetPanel";
import { snapshotParams } from "@/lib/snapshot-params";

export function generateStaticParams() {
  return snapshotParams("assets");
}

export default function AssetPage({ params }: PageProps<"/assets/[id]">) {
  return (
    <Suspense fallback={<p className="px-4 py-6 text-muted">Loading…</p>}>
      {params.then(({ id }) => (
        <AssetPanel assetId={id} />
      ))}
    </Suspense>
  );
}
