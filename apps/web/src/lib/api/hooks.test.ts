import { describe, expect, it } from "vitest";

import { applyRunEvent, type RunProgress } from "./hooks";

const start: RunProgress = { status: "connecting", stages: {} };

describe("applyRunEvent", () => {
  it("follows a run from start to success", () => {
    let p = applyRunEvent(start, { type: "run.started" });
    p = applyRunEvent(p, { type: "stage.started", stage: "ingest" });
    expect(p.status).toBe("running");
    expect(p.stages.ingest.status).toBe("running");
    p = applyRunEvent(p, { type: "stage.progress", stage: "ingest", counts: { embeddings_computed: 1 } });
    expect(p.stages.ingest).toEqual({ status: "running", counts: { embeddings_computed: 1 } });
    p = applyRunEvent(p, { type: "stage.succeeded", stage: "ingest", counts: { embeddings_computed: 1 } });
    p = applyRunEvent(p, { type: "run.succeeded" });
    expect(p.status).toBe("succeeded");
    expect(p.stages.ingest.status).toBe("succeeded");
  });

  it("keeps the failing stage and its error", () => {
    let p = applyRunEvent(start, { type: "stage.failed", stage: "ingest", detail: { error: "RuntimeError: boom" } });
    p = applyRunEvent(p, { type: "run.failed", detail: { error: "stage ingest failed: RuntimeError: boom" } });
    expect(p.stages.ingest.status).toBe("failed");
    expect(p.status).toBe("failed");
    expect(p.error).toBe("stage ingest failed: RuntimeError: boom");
  });

  it("marks stages finished by an earlier attempt as skipped", () => {
    const p = applyRunEvent(start, { type: "stage.skipped", stage: "ingest" });
    expect(p.stages.ingest.status).toBe("skipped");
  });

  it("ignores unknown events", () => {
    expect(applyRunEvent(start, { type: "something.else" })).toBe(start);
  });
});
