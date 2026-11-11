"use client";

import { useId, type ReactNode } from "react";

import { GLOSSARY, type GlossaryKey } from "@/lib/explain";

/**
 * A defined term. Its plain-language definition appears on hover or keyboard focus, so a
 * reader new to provenance work can read the console without a manual.
 */
export function Term({ name, children }: { name: GlossaryKey; children?: ReactNode }) {
  const id = useId();
  return (
    <span className="group relative inline-block">
      <span tabIndex={0} aria-describedby={id} className="term outline-none focus-visible:outline-2">
        {children ?? name.replace("_", " ")}
      </span>
      <span
        id={id}
        role="tooltip"
        className="pointer-events-none invisible absolute left-0 top-full z-50 mt-1 w-72 border border-line bg-surface-3 px-2.5 py-2 text-[12px] font-normal normal-case leading-snug tracking-normal text-text opacity-0 shadow-none group-focus-within:visible group-focus-within:opacity-100 group-hover:visible group-hover:opacity-100"
      >
        {GLOSSARY[name]}
      </span>
    </span>
  );
}
