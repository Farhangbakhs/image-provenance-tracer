import { SystemStatus } from "@/components/SystemStatus";
import { EARLIEST_DISCLAIMER } from "@/lib/copy";

export default function Home() {
  return (
    <section className="mx-auto w-full max-w-3xl px-4 py-10">
      <h1 className="text-[15px] font-semibold">Image provenance tracer</h1>
      <p className="mt-2 max-w-prose text-muted">
        ORIGIN finds where an image has appeared, verifies each copy against the original, dates every
        sighting as an interval with a stated confidence, and shows where the story told about the image
        diverges. Every statement cites stored evidence.
      </p>
      <p className="mt-6 border-l border-accent pl-3 text-[12px] text-muted">{EARLIEST_DISCLAIMER}</p>
      <div className="mt-8 max-w-md">
        <SystemStatus />
      </div>
    </section>
  );
}
