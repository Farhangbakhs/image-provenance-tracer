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
      counts: { pending: 0, verified: 1, unrelated: 0, fetch_failed: 1 },
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

  it("shows nothing when every checked hit matched", async () => {
    respond({ run_id: "r1", counts: { pending: 0, verified: 2, unrelated: 0, fetch_failed: 0 }, rejected: [] });
    const { container } = renderPanel();
    await new Promise((r) => setTimeout(r, 20));
    expect(container.textContent).toBe("");
  });
});
