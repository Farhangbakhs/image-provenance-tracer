import type { RunProgress, StageStatus } from "@/lib/api/hooks";

const LABELS: Record<StageStatus | "not_run", string> = {
  pending: "waiting",
  running: "running",
  succeeded: "done",
  skipped: "done earlier",
  failed: "failed",
  not_run: "not run",
};

/** The pipeline's stages in order, with each one's state in this run. */
export function StageStrip({ order, progress }: { order: string[]; progress?: RunProgress }) {
  const finished = progress?.status === "succeeded" || progress?.status === "failed";
  return (
    <ol className="grid grid-cols-3 gap-px border-t border-line bg-line sm:grid-cols-6" aria-label="Pipeline stages">
      {order.map((stage) => {
        const state = progress?.stages[stage];
        const status: StageStatus | "not_run" = state?.status ?? (finished ? "not_run" : "pending");
        const counts = state ? Object.entries(state.counts) : [];
        return (
          <li key={stage} className="bg-surface-1 px-2 py-2" aria-current={status === "running" ? "step" : undefined}>
            <div className="text-[11px] uppercase tracking-[0.1em] text-muted">{stage}</div>
            <div className={`mono text-[12px] ${status === "failed" ? "font-semibold" : ""}`}>{LABELS[status]}</div>
            {counts.length ? (
              <div className="mono text-[11px] text-muted">
                {counts.map(([name, value]) => `${name.replaceAll("_", " ")} ${value}`).join(", ")}
              </div>
            ) : null}
          </li>
        );
      })}
    </ol>
  );
}
