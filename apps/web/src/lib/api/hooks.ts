"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { API_URL, api, type AssetOut, type CaseOut, type RunOut } from "./client";

/** An error with the API's explanation, so the UI can show why something was refused. */
export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly reason?: string,
  ) {
    super(message);
  }
}

function fail(status: number, body: unknown, fallback: string): never {
  const detail = body as { message?: string; detail?: unknown; reason?: string } | undefined;
  const message =
    detail?.message ?? (typeof detail?.detail === "string" ? detail.detail : undefined) ?? fallback;
  throw new ApiError(message, status, detail?.reason);
}

export function useCases() {
  return useQuery({
    queryKey: ["cases"],
    queryFn: async ({ signal }) => {
      const { data, error, response } = await api.GET("/cases", { signal });
      if (!data) fail(response.status, error, "Could not load cases");
      return data;
    },
  });
}

export function useCase(caseId: string) {
  return useQuery({
    queryKey: ["case", caseId],
    queryFn: async ({ signal }) => {
      const { data, error, response } = await api.GET("/cases/{case_id}", {
        params: { path: { case_id: caseId } },
        signal,
      });
      if (!data) fail(response.status, error, "Could not load the case");
      return data;
    },
  });
}

export function useAsset(assetId: string) {
  return useQuery({
    queryKey: ["asset", assetId],
    queryFn: async ({ signal }) => {
      const { data, error, response } = await api.GET("/assets/{asset_id}", {
        params: { path: { asset_id: assetId } },
        signal,
      });
      if (!data) fail(response.status, error, "Could not load the image");
      return data;
    },
  });
}

export async function createCase(title: string, notes?: string): Promise<CaseOut> {
  const { data, error, response } = await api.POST("/cases", { body: { title, notes: notes ?? null } });
  if (!data) fail(response.status, error, "Could not create the case");
  return data;
}

/** Multipart upload; the API decides what the file is from its bytes, not its name. */
export async function uploadAsset(caseId: string, file: File): Promise<AssetOut> {
  const form = new FormData();
  form.append("file", file, file.name);
  const response = await globalThis.fetch(`${API_URL}/cases/${caseId}/assets`, {
    method: "POST",
    body: form,
  });
  const body: unknown = await response.json().catch(() => undefined);
  if (!response.ok) fail(response.status, body, `Upload failed (HTTP ${response.status})`);
  return body as AssetOut;
}

export function useUploadToCase(caseId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (file: File) => uploadAsset(caseId, file),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["case", caseId] }),
  });
}

export function useStartRun(assetId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (): Promise<RunOut> => {
      const { data, error, response } = await api.POST("/assets/{asset_id}/runs", {
        params: { path: { asset_id: assetId } },
      });
      if (!data) fail(response.status, error, "Could not start the trace");
      return data;
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["asset", assetId] }),
  });
}

export type StageStatus = "pending" | "running" | "succeeded" | "skipped" | "failed";

export interface RunProgress {
  status: "connecting" | "running" | "succeeded" | "failed";
  stages: Record<string, { status: StageStatus; counts: Record<string, number> }>;
  error?: string;
}

interface StreamEvent {
  type: string;
  stage?: string | null;
  counts?: Record<string, number>;
  detail?: { error?: string | null };
}

/** Apply one run event to the progress state. Pure, so it can be tested without a server. */
export function applyRunEvent(progress: RunProgress, event: StreamEvent): RunProgress {
  const stages = { ...progress.stages };
  const stage = event.stage ?? undefined;
  const set = (status: StageStatus) => {
    if (stage) stages[stage] = { status, counts: { ...stages[stage]?.counts, ...event.counts } };
  };
  switch (event.type) {
    case "run.started":
      return { ...progress, status: "running", stages };
    case "stage.started":
      set("running");
      return { ...progress, stages };
    case "stage.progress":
      set(stages[stage ?? ""]?.status ?? "running");
      return { ...progress, stages };
    case "stage.succeeded":
      set("succeeded");
      return { ...progress, stages };
    case "stage.skipped":
      set("skipped");
      return { ...progress, stages };
    case "stage.failed":
      set("failed");
      return { ...progress, stages, error: event.detail?.error ?? undefined };
    case "run.succeeded":
      return { ...progress, status: "succeeded", stages };
    case "run.failed":
      return { ...progress, status: "failed", stages, error: event.detail?.error ?? progress.error };
    default:
      return progress;
  }
}

const EVENT_TYPES = [
  "run.started",
  "run.succeeded",
  "run.failed",
  "stage.started",
  "stage.progress",
  "stage.succeeded",
  "stage.skipped",
  "stage.failed",
] as const;

/** Live progress of a run over server-sent events. The browser resumes on reconnect. */
export function useRunProgress(runId: string | undefined, onFinished?: () => void): RunProgress | undefined {
  // Progress is stored with the run it belongs to, so switching runs starts from "connecting"
  // without resetting state inside the effect.
  const [state, setState] = useState<{ runId?: string; progress?: RunProgress }>({});

  useEffect(() => {
    if (!runId) return;
    const source = new EventSource(`${API_URL}/runs/${runId}/events`);
    const handle = (message: MessageEvent<string>) => {
      const event = JSON.parse(message.data) as StreamEvent;
      setState((current) => ({
        runId,
        progress: applyRunEvent(
          current.runId === runId && current.progress ? current.progress : { ...CONNECTING },
          event,
        ),
      }));
      if (event.type === "run.succeeded" || event.type === "run.failed") {
        source.close();
        onFinished?.();
      }
    };
    for (const type of EVENT_TYPES) source.addEventListener(type, handle);
    return () => source.close();
    // onFinished is a callback; re-subscribing when it changes identity would restart the stream.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId]);

  if (!runId) return undefined;
  return state.runId === runId && state.progress ? state.progress : CONNECTING;
}

const CONNECTING: RunProgress = { status: "connecting", stages: {} };

export function useRunSightings(runId: string | undefined) {
  return useQuery({
    queryKey: ["sightings", runId],
    enabled: Boolean(runId),
    queryFn: async ({ signal }) => {
      const { data, error, response } = await api.GET("/runs/{run_id}/sightings", {
        params: { path: { run_id: runId as string } },
        signal,
      });
      if (!data) fail(response.status, error, "Could not load sightings");
      return data;
    },
  });
}

export function useRunAnalysis(runId: string | undefined) {
  return useQuery({
    queryKey: ["analysis", runId],
    enabled: Boolean(runId),
    queryFn: async ({ signal }) => {
      const { data, error, response } = await api.GET("/runs/{run_id}/analysis", {
        params: { path: { run_id: runId as string } },
        signal,
      });
      if (!data) fail(response.status, error, "Could not load the analysis");
      return data;
    },
  });
}

export function useRun(runId: string) {
  return useQuery({
    queryKey: ["run", runId],
    queryFn: async ({ signal }) => {
      const { data, error, response } = await api.GET("/runs/{run_id}", {
        params: { path: { run_id: runId } },
        signal,
      });
      if (!data) fail(response.status, error, "Could not load the run");
      return data;
    },
  });
}

export function useOverrule(runId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: { kind: "claim" | "sighting"; id: string; status: "accepted" | "overruled"; note?: string }) => {
      const body = { status: input.status, note: input.note ?? null };
      const result =
        input.kind === "claim"
          ? await api.PATCH("/claims/{claim_id}", { params: { path: { claim_id: input.id } }, body })
          : await api.PATCH("/sightings/{sighting_id}", { params: { path: { sighting_id: input.id } }, body });
      if (result.error) fail(result.response.status, result.error, "Could not record the decision");
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["sightings", runId] });
      void queryClient.invalidateQueries({ queryKey: ["analysis", runId] });
    },
  });
}

/** The run's evidence pack: findings plus every artefact with its hash and fetch time. */
export function useEvidencePack(runId: string) {
  return useQuery({
    queryKey: ["evidence-pack", runId],
    queryFn: async ({ signal }) => {
      const { data, error, response } = await api.GET("/runs/{run_id}/evidence-pack", {
        params: { path: { run_id: runId } },
        signal,
      });
      if (!data) fail(response.status, error, "Could not load the evidence pack");
      return data;
    },
  });
}
