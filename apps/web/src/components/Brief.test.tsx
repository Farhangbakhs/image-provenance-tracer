import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import type { EvidencePack, SightingOut } from "@/lib/api/client";

import { BriefDocument } from "./Brief";

function sighting(id: string, domain: string, upper: string): SightingOut {
  return {
    id,
    provider: "demo-index",
    page_url: `https://${domain}/p`,
    image_url: `https://${domain}/i.jpg`,
    domain,
    title: null,
    match_class: "near_duplicate",
    match_reason: null,
    sscd_cosine: 0.97,
    phash_distance: 2,
    pdq_distance: 10,
    transform: null,
    threshold_version: "match.v2",
    date_lower: null,
    date_upper: upper,
    date_confidence: "high",
    dating_rule_version: "dating.v1",
    deciding: null,
    evidence: [],
    image_url_local: `/sightings/${id}/image`,
    reliability: "F",
    credibility: 2,
    analyst_status: "accepted",
  };
}

const llm = { llm_provider: "gemini", llm_model: "gemini-3.5-flash-lite" };
const claimNulls = { event: null, place: null, claimed_date: null, actor_role: null, stance: null, language: null, translation: null, analyst_note: null };
const narrativeNulls = { summary: null, parent_narrative_id: null, divergence_reason: null };

const pack: EvidencePack = {
  format: "origin.evidence-pack.v1",
  generated_at: "2026-11-11T10:00:00Z",
  disclaimer: "Earliest found in indexed sources. Earlier copies may exist.",
  case: { id: "case", title: "Flood photo", notes: null },
  asset: {
    id: "asset",
    original_filename: "q.jpg",
    content_type: "image/jpeg",
    width: 640,
    height: 480,
    sha256: "a".repeat(64),
    phash: "0".repeat(16),
    dhash: "0".repeat(16),
    pdq: "0".repeat(64),
    embedding_model: "sscd",
    original_artefact_id: "art1",
    display_artefact_id: null,
  },
  run: {
    id: "run",
    case_id: "case",
    asset_id: "asset",
    status: "succeeded",
    providers: ["demo-index"],
    stages: {},
    stage_order: [],
    error: null,
    created_at: "2026-11-11T09:00:00Z",
    started_at: null,
    finished_at: null,
  },
  sightings: {
    run_id: "run",
    status: "succeeded",
    earliest_sighting_id: "s1",
    candidates: { pending: 0, verified: 2, unrelated: 1, fetch_failed: 0 },
    notes: {},
    sightings: [sighting("s1", "valencia.example", "2024-10-30T08:15:00Z"), sighting("s2", "viral.example", "2024-11-12T09:00:00Z")],
  },
  analysis: {
    run_id: "run",
    variants: [],
    edges: [],
    propagation: [],
    claims: [
      { id: "c1", sighting_id: "s1", quote: "Floodwater fills a street in Valencia", quote_start: 0, quote_end: 37, prompt_version: "claim.v1", analyst_status: "accepted", ...claimNulls, ...llm },
      { id: "c2", sighting_id: "s2", quote: "Hurricane Milton flooding a street in Tampa", quote_start: 0, quote_end: 43, prompt_version: "claim.v1", analyst_status: "accepted", ...claimNulls, ...llm },
    ],
    narratives: [
      { ...narrativeNulls, id: "n1", label: "Valencia floods", divergence_sighting_id: "s1", claim_ids: ["c1"], prompt_version: "narrative.v1", ...llm },
      { ...narrativeNulls, id: "n2", label: "Hurricane Milton", parent_narrative_id: "n1", divergence_sighting_id: "s2", divergence_reason: "places it in Florida", claim_ids: ["c2"], prompt_version: "narrative.v1", ...llm },
    ],
    grades: [],
    notes: {},
  },
  provider_calls: [],
  artefacts: [
    { id: "art1", kind: "upload", sha256: "a".repeat(64), storage_key: "sha256/aa", content_type: "image/jpeg", byte_size: 10, source_url: null, http_status: null, fetched_at: "2026-11-11T09:00:00Z" },
  ],
  audit: [],
};

afterEach(cleanup);

describe("BriefDocument", () => {
  it("states the earliest found sighting with the disclaimer and cites sightings by reference", () => {
    render(<BriefDocument pack={pack} />);
    expect(screen.getByText(/Earliest found:/).parentElement?.textContent).toContain("S1 on valencia.example");
    expect(screen.getByText("Earliest found in indexed sources. Earlier copies may exist.")).toBeTruthy();
    expect(screen.getByText(/Diverges at S2/).textContent).toContain("places it in Florida");
    expect(screen.getByText(/Hurricane Milton flooding/).textContent).toContain("[S2]");
    expect(screen.getAllByText("a".repeat(64)).length).toBeGreaterThan(0);
  });
});
