"use client";

import { EARLIEST_DISCLAIMER } from "@/lib/copy";
import type { RunSummary } from "@/lib/summary";

/**
 * The answer, before anything else: one sentence built from stored fields, and under it the
 * limits of that answer and the counts behind it. The domain selects its copy.
 */
export function AnswerSummary({
  summary,
  imageUrl,
  onSelect,
  onDetails,
}: {
  summary: RunSummary;
  imageUrl: string | null;
  onSelect: (sightingId: string) => void;
  onDetails: () => void;
}) {
  return (
    <section aria-label="Summary" className="flex items-start gap-4 border border-line bg-surface-1 p-4">
      {imageUrl ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={imageUrl} alt="Your image" className="h-14 w-20 shrink-0 border border-line object-cover" />
      ) : null}
      <div className="min-w-0 flex-1">
        <p className="text-[15px] font-medium leading-snug">
          {summary.parts.map((part, i) =>
            "text" in part ? (
              <span key={i}>{part.text}</span>
            ) : (
              <button
                key={i}
                type="button"
                onClick={() => onSelect(part.sightingId)}
                className="underline decoration-line underline-offset-4 hover:decoration-text"
              >
                {part.domain}
              </button>
            ),
          )}
        </p>
        <p className="mt-1 text-[12px] tabular-nums text-muted">
          {EARLIEST_DISCLAIMER} · {summary.facts.join(" · ")} ·{" "}
          <button type="button" onClick={onDetails} className="underline underline-offset-2 hover:text-text">
            details
          </button>
        </p>
      </div>
    </section>
  );
}
