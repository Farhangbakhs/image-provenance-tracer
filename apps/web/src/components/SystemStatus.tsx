"use client";

import { useQuery } from "@tanstack/react-query";

import { DEPENDENCY_LABELS, fetchReadiness } from "@/lib/readiness";

/** Live readiness of the API and its stores, polled every 10 seconds. */
export function SystemStatus() {
  const { data, isPending } = useQuery({
    queryKey: ["readyz"],
    queryFn: ({ signal }) => fetchReadiness(signal),
    refetchInterval: 10_000,
  });

  return (
    <section aria-labelledby="system-status" className="border border-line bg-surface-1">
      <header className="flex items-center justify-between border-b border-line px-3 py-2">
        <h2 id="system-status" className="text-[11px] font-semibold uppercase tracking-[0.12em] text-muted">
          System
        </h2>
        <span className="mono text-[11px] text-muted" aria-live="polite">
          {isPending
            ? "checking"
            : data?.kind === "ready"
              ? "ready"
              : data?.kind === "degraded"
                ? "degraded"
                : "API unreachable"}
        </span>
      </header>
      {data && data.kind !== "unreachable" ? (
        <dl className="divide-y divide-line">
          {Object.entries(data.body.checks).map(([name, check]) => (
            <div key={name} className="grid grid-cols-[1fr_auto_auto] gap-4 px-3 py-1.5">
              <dt>{DEPENDENCY_LABELS[name] ?? name}</dt>
              <dd className="mono text-muted">{check.latency_ms} ms</dd>
              <dd className={check.ok ? "mono text-muted" : "mono font-semibold text-text"}>
                {check.ok ? "ok" : "down"}
              </dd>
              {!check.ok && check.error ? (
                <dd className="mono col-span-3 break-all text-[11px] text-muted">{check.error}</dd>
              ) : null}
            </div>
          ))}
        </dl>
      ) : null}
      {data?.kind === "unreachable" ? (
        <p className="mono px-3 py-2 text-[11px] text-muted">{data.message}</p>
      ) : null}
    </section>
  );
}
