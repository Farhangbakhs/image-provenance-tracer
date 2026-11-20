import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { CandidatesPanel } from "./CandidatesPanel";

function renderPanel() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <CandidatesPanel runId="r1" />
    </QueryClientProvider>,
  );
}

function respond(body: unknown) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } })),
  );
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("CandidatesPanel", () => {
  it("lists each rejected hit with why, and links the stored page", async () => {
    respond({
      run_id: "r1",
      counts: { pending: 0, verified: 1, unrelated: 0, fetch_failed: 1, blocked: 0 },
      unchecked: [],
      check_limit: 50,
      rejected: [
        {
          id: "c1",
          rank: 3,
          provider: "lens",
          source: "The New York Times",
          title: "A story",
          provider_url: "https://www.nytimes.com/x",
          status: "fetch_failed",
          reason: "page HTTP 403",
          fetch_info: { page: { status: 403, final_url: "https://www.nytimes.com/x", bytes: 771 } },
          page_local: "/candidates/c1/page",
        },
      ],
    });
    renderPanel();
    expect(await screen.findByText("Checked, not matched (1)")).toBeTruthy();
    expect(screen.getByText("The New York Times")).toBeTruthy();
    expect(screen.getByText(/refused ORIGIN's request \(HTTP 403\)/)).toBeTruthy();
    const link = screen.getByRole("link", { name: /View the stored page/ });
    expect(link.getAttribute("href")).toContain("/candidates/c1/page");
  });

  it("lists the hits that were never checked, with the count and why", async () => {
    const hit = (rank: number, source: string) => ({
      id: `u${rank}`,
      rank,
      provider: "lens",
      source,
      title: `Story ${rank}`,
      provider_url: `https://x.example/${rank}`,
      status: "pending",
      reason: "not checked: beyond the top 50 hits",
      fetch_info: null,
      page_local: null,
    });
    respond({
      run_id: "r1",
      counts: { pending: 2, verified: 4, unrelated: 0, fetch_failed: 0, blocked: 0 },
      rejected: [],
      unchecked: [hit(51, "Late News"), hit(52, "Later News")],
      check_limit: 50,
    });
    renderPanel();
    expect(await screen.findByText("Not checked (2)")).toBeTruthy();
    expect(screen.getByText(/opens the 50 best-ranked hits/)).toBeTruthy();
    expect(screen.getByText("Late News")).toBeTruthy();
    expect(screen.getByText("Later News")).toBeTruthy();
    expect(screen.queryByText(/Checked, not matched/)).toBeNull();
  });

  it("shows nothing when every checked hit matched", async () => {
    respond({
      run_id: "r1",
      counts: { pending: 0, verified: 2, unrelated: 0, fetch_failed: 0, blocked: 0 },
      rejected: [],
      unchecked: [],
      check_limit: 50,
    });
    const { container } = renderPanel();
    await new Promise((r) => setTimeout(r, 20));
    expect(container.textContent).toBe("");
  });
});
