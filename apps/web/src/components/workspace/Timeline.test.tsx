import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { SightingOut } from "@/lib/api/client";
import { buildWorkspace } from "@/lib/workspace";

import { Timeline } from "./Timeline";

afterEach(cleanup);

const s = (id: string, lower: string | null, upper: string): SightingOut =>
  ({ id, date_lower: lower, date_upper: upper, date_confidence: "medium", domain: `${id}.example` }) as SightingOut;

describe("Timeline", () => {
  it("draws one marker per sighting, pins the earliest and reports clicks", () => {
    const model = buildWorkspace(
      {
        run_id: "r",
        status: "succeeded",
        earliest_sighting_id: "a",
        candidates: { pending: 0, verified: 2, unrelated: 0, fetch_failed: 0 },
        notes: {},
        sightings: [s("a", "2024-03-05T09:00:00Z", "2024-03-06T12:00:00Z"), s("b", null, "2024-04-01T00:00:00Z")],
      },
      undefined,
    );
    const onSelect = vi.fn();
    render(<Timeline model={model} selected={null} onSelect={onSelect} />);
    expect(screen.getByText("earliest found")).toBeTruthy();
    const marker = screen.getByRole("button", { name: /a\.example: between 2024-03-05 09:00Z and 2024-03-06 12:00Z/ });
    fireEvent.click(marker);
    expect(onSelect).toHaveBeenCalledWith("a");
    expect(screen.getByRole("button", { name: /b\.example: no later than 2024-04-01/ })).toBeTruthy();
  });
});
