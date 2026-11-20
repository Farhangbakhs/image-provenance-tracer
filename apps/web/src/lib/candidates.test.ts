import { describe, expect, it } from "vitest";

import type { CandidateOut } from "./api/client";
import { readCandidate } from "./candidates";

const base: CandidateOut = {
  id: "c1",
  rank: 7,
  provider: "lens",
  source: "ProPublica",
  title: "A story",
  provider_url: "https://www.google.com/goto?url=abc",
  status: "unrelated",
  reason: null,
  fetch_info: null,
  page_local: null,
};

describe("readCandidate", () => {
  it("says a page with no images loaded and was empty of pictures", () => {
    const r = readCandidate({
      ...base,
      reason: "no image on the page (HTTP 200, text/html, 4,201 bytes)",
      fetch_info: { page: { status: 200, final_url: "https://x.example/a", content_type: "text/html", bytes: 4201, images_found: 0 } },
    });
    expect(r.headline).toBe("The page loaded, but ORIGIN found no image on it to compare.");
    expect(r.facts).toContainEqual({ label: "Page", value: "HTTP 200" });
    expect(r.facts).toContainEqual({ label: "Final URL", value: "https://x.example/a" });
    expect(r.facts).toContainEqual({ label: "Images found", value: "0" });
  });

  it("says when a site refused the request", () => {
    const r = readCandidate({ ...base, status: "fetch_failed", reason: "page HTTP 403", fetch_info: { page: { status: 403 } } });
    expect(r.headline).toContain("refused ORIGIN's request (HTTP 403)");
  });

  it("reports an unreachable page with its error", () => {
    const r = readCandidate({
      ...base,
      status: "fetch_failed",
      reason: "page fetch failed: timed out",
      fetch_info: { page: { status: null, error: "page fetch failed: timed out" } },
    });
    expect(r.headline).toBe("The page could not be fetched.");
    expect(r.facts).toContainEqual({ label: "Error", value: "page fetch failed: timed out" });
  });

  it("counts the images that were compared", () => {
    const r = readCandidate({
      ...base,
      reason: "SSCD 0.006 < 0.5",
      fetch_info: { page: { status: 200, images_found: 2 }, images: [{ url: "a" }, { url: "b" }] },
    });
    expect(r.headline).toBe("Compared 2 images on the page; none matched your picture.");
  });
});
