import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import type { RunSightingsOut, SightingOut } from "@/lib/api/client";

import { SightingsList } from "./SightingsPanel";

function sighting(id: string, domain: string, over: Partial<SightingOut> = {}): SightingOut {
  return {
    id,
    provider: "vision",
    page_url: `https://${domain}/p`,
    image_url: `https://${domain}/i.jpg`,
    domain,
    title: null,
    match_class: "near_duplicate",
    match_reason: "pHash 2 <= 8",
    sscd_cosine: 0.97,
    phash_distance: 2,
    pdq_distance: 10,
    transform: null,
    threshold_version: "match.v2",
    date_lower: null,
    date_upper: "2024-03-20T00:00:00Z",
    date_confidence: "high",
    dating_rule_version: "dating.v1",
    deciding: null,
    evidence: [],
    image_url_local: `/sightings/${id}/image`,
    analyst_status: "accepted",
    ...over,
  };
}

afterEach(cleanup);

describe("SightingsList", () => {
  it("marks the earliest found sighting and shows the disclaimer", () => {
    const data: RunSightingsOut = {
      run_id: "r",
      status: "succeeded",
      earliest_sighting_id: "a",
      candidates: { pending: 0, verified: 2, unrelated: 3, fetch_failed: 1 },
      notes: { lens: "not queried: SERPAPI_API_KEY is not set" },
      sightings: [
        sighting("a", "news.example", {
          date_lower: "2024-03-05T09:00:00Z",
          date_upper: "2024-03-06T12:00:00Z",
          date_confidence: "medium",
          match_class: "derivative",
          transform: { edits: ["crop", "overlay"] },
          deciding: {
            id: "e",
            kind: "page_metadata",
            value: "2024-03-05T09:00:00Z",
            bound: "claimed",
            confidence: "medium",
            source_url: null,
            detail: {},
          },
        }),
        sighting("b", "cdn.example"),
      ],
    };
    render(<SightingsList data={data} />);
    expect(screen.getByText("earliest found")).toBeTruthy();
    expect(screen.getByText(/Earliest found in indexed sources/)).toBeTruthy();
    expect(screen.getByText("2 verified · 4 rejected of 6 candidates")).toBeTruthy();
    expect(screen.getByText(/between 2024-03-05 09:00Z and 2024-03-06 12:00Z/)).toBeTruthy();
    expect(screen.getByText(/Edited copy: cropped, text or graphics added. First online between .*page's stated date/)).toBeTruthy();
    expect(screen.getByText(/no later than 2024-03-20 00:00Z/)).toBeTruthy();
    expect(screen.getByText(/SERPAPI_API_KEY is not set/)).toBeTruthy();
    const link = screen.getByText("news.example").closest("a") as HTMLAnchorElement;
    expect(link.rel).toContain("noopener");
  });

  it("explains an empty result instead of implying the image is unique", () => {
    render(
      <SightingsList
        data={{
          run_id: "r",
          status: "succeeded",
          earliest_sighting_id: null,
          candidates: { pending: 0, verified: 0, unrelated: 0, fetch_failed: 0 },
          notes: { providers: "no provider is enabled, so nothing was searched" },
          sightings: [],
        }}
      />,
    );
    expect(screen.getByText(/No verified sightings/)).toBeTruthy();
    expect(screen.getByText(/nothing was searched/)).toBeTruthy();
    expect(screen.queryByText(/Earliest found in indexed sources/)).toBeNull();
  });
});
