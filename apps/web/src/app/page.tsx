import { Intake, RecentCases } from "@/components/Intake";
import { Panel } from "@/components/Panel";
import { SystemStatus } from "@/components/SystemStatus";
import { Term } from "@/components/ui/Term";
import { SNAPSHOT } from "@/lib/api/client";

const STEPS = [
  {
    title: "Search",
    body: "Reverse-image engines (Google Lens, and a watchlist of public Telegram channels when enabled) are asked where the picture appears. Every hit is only a candidate.",
  },
  {
    title: "Verify",
    body: "ORIGIN fetches each candidate itself and compares it with your picture: identical file, same picture, or an edited copy (crop, mirror, caption). Everything else is rejected.",
  },
  {
    title: "Date",
    body: "Each copy gets a date range from archive captures, platform timestamps, page metadata and file metadata, with the evidence that decided it and a confidence.",
  },
  {
    title: "Explain",
    body: "Copies are grouped into variants, the stories told about the picture are compared, and the points where the story changes are marked.",
  },
];

export default function Home() {
  return (
    <div className="mx-auto grid w-full max-w-6xl gap-4 px-4 py-6 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
      <div className="flex min-w-0 flex-col gap-4">
        <header>
          <p className="label">Open-source investigation</p>
          <h1 className="mt-1 text-[22px] font-semibold tracking-tight">Where has this picture been, and since when?</h1>
          <p className="mt-2 max-w-prose text-muted">
            ORIGIN traces an image across the web: it finds copies, proves each one is the same picture, dates it as a
            range with stated confidence, and shows where the story told about it changed. Every statement links to
            stored evidence. It reports the <Term name="earliest">earliest copy found</Term>, never an &ldquo;origin&rdquo;.
          </p>
        </header>
        <Panel title="How a trace works">
          <ol className="grid gap-px bg-line sm:grid-cols-2">
            {STEPS.map((step, i) => (
              <li key={step.title} className="bg-surface-1 px-3 py-3">
                <div className="flex items-baseline gap-2">
                  <span className="mono text-[12px] text-intent">0{i + 1}</span>
                  <span className="font-semibold">{step.title}</span>
                </div>
                <p className="mt-1 text-[13px] text-muted">{step.body}</p>
              </li>
            ))}
          </ol>
        </Panel>
        {SNAPSHOT ? (
          <Panel title="This is a snapshot">
            <p className="px-3 py-3 text-[13px] text-muted">
              A read-only copy of four demo investigations, so it runs without a server. Open a case on the right to
              explore it. The web pages, Telegram channels and dates in these cases are synthetic; everything ORIGIN
              computed from them is real output of the pipeline. To trace your own images, run ORIGIN locally.
            </p>
          </Panel>
        ) : (
          <Intake />
        )}
      </div>
      <div className="flex min-w-0 flex-col gap-4">
        <RecentCases />
        {SNAPSHOT ? null : <SystemStatus />}
      </div>
    </div>
  );
}
