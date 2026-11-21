import type { ReactNode } from "react";

/** A bordered console panel with a small uppercase heading. */
export function Panel({
  title,
  aside,
  hint,
  children,
}: {
  title: string;
  aside?: ReactNode;
  /** One plain sentence on what this panel shows and how to read it. */
  hint?: ReactNode;
  children: ReactNode;
}) {
  const id = `panel-${title.toLowerCase().replace(/[^a-z0-9]+/g, "-")}`;
  return (
    <section aria-labelledby={id} className="border border-line bg-surface-1">
      <header className="flex items-center justify-between gap-3 border-b border-line bg-surface-2 px-3 py-2">
        <h2 id={id} className="label text-text">
          {title}
        </h2>
        {aside ? <div className="mono text-[12px] text-muted">{aside}</div> : null}
      </header>
      {hint ? <p className="border-b border-line px-3 py-2 text-[13px] text-muted">{hint}</p> : null}
      {children}
    </section>
  );
}

/** A panel that starts closed: the heading is the toggle, and a count or note can sit beside it. */
export function FoldPanel({
  title,
  note,
  children,
}: {
  title: string;
  /** Shown on the heading line while the panel is closed, so it says what is inside. */
  note?: string;
  children: ReactNode;
}) {
  return (
    <details className="group border border-line bg-surface-1">
      <summary className="flex cursor-pointer list-none items-center gap-3 bg-surface-2 px-3 py-2 hover:bg-surface-1 [&::-webkit-details-marker]:hidden">
        <span aria-hidden className="text-[10px] text-muted transition-transform group-open:rotate-90 motion-reduce:transition-none">
          ▶
        </span>
        <h2 className="label shrink-0 whitespace-nowrap text-text">{title}</h2>
        {note ? <span className="truncate text-[12px] text-muted group-open:hidden">{note}</span> : null}
      </summary>
      <div className="border-t border-line">{children}</div>
    </details>
  );
}

/** Label/value rows. Values in `mono` are hashes, ids, times or coordinates. */
export function Fields({ rows }: { rows: Array<{ label: string; value: ReactNode; mono?: boolean }> }) {
  return (
    <dl className="divide-y divide-line">
      {rows.map((row) => (
        <div key={row.label} className="grid grid-cols-[10rem_1fr] gap-3 px-3 py-2">
          <dt className="text-muted">{row.label}</dt>
          <dd className={row.mono ? "mono min-w-0 break-all text-[13px]" : "min-w-0 break-words"}>
            {row.value ?? <span className="text-muted">—</span>}
          </dd>
        </div>
      ))}
    </dl>
  );
}
