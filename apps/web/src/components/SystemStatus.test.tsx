import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { SystemStatus } from "./SystemStatus";

function renderWithClient() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <SystemStatus />
    </QueryClientProvider>,
  );
}

function respond(status: number, body: unknown) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } })),
  );
}

const check = (ok: boolean, error?: string) => ({ ok, latency_ms: 3, error: error ?? null });

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("SystemStatus", () => {
  it("shows every dependency when the API is ready", async () => {
    respond(200, {
      status: "ok",
      version: "0.1.0",
      checks: { database: check(true), redis: check(true), storage: check(true) },
    });
    renderWithClient();
    expect(await screen.findByText("ready")).toBeTruthy();
    expect(screen.getByText("Database")).toBeTruthy();
    expect(screen.getByText("Object storage")).toBeTruthy();
    expect(screen.getAllByText("ok")).toHaveLength(3);
  });

  it("names the failing dependency on a 503", async () => {
    respond(503, {
      status: "degraded",
      version: "0.1.0",
      checks: { database: check(true), redis: check(false, "ConnectionError: refused"), storage: check(true) },
    });
    renderWithClient();
    expect(await screen.findByText("degraded")).toBeTruthy();
    expect(screen.getByText("down")).toBeTruthy();
    expect(screen.getByText("ConnectionError: refused")).toBeTruthy();
  });

  it("reports an unreachable API", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => Promise.reject(new TypeError("Failed to fetch"))));
    renderWithClient();
    expect(await screen.findByText("API unreachable")).toBeTruthy();
    expect(screen.getByText("Failed to fetch")).toBeTruthy();
  });
});
