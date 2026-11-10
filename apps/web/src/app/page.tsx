import { Intake, RecentCases } from "@/components/Intake";
import { SystemStatus } from "@/components/SystemStatus";
import { EARLIEST_DISCLAIMER } from "@/lib/copy";

export default function Home() {
  return (
    <div className="mx-auto grid w-full max-w-5xl gap-4 px-4 py-6 md:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
      <div className="flex min-w-0 flex-col gap-4">
        <header>
          <h1 className="text-[15px] font-semibold">Image provenance tracer</h1>
          <p className="mt-1 max-w-prose text-muted">
            ORIGIN finds where an image has appeared, verifies each copy against the original, dates every
            sighting as an interval with a stated confidence, and shows where the story told about the image
            diverges. Every statement cites stored evidence.
          </p>
          <p className="mt-3 border-l border-accent pl-3 text-[12px] text-muted">{EARLIEST_DISCLAIMER}</p>
        </header>
        <Intake />
      </div>
      <div className="flex min-w-0 flex-col gap-4">
        <RecentCases />
        <SystemStatus />
      </div>
    </div>
  );
}
