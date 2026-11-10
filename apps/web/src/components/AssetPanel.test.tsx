import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { AssetOut } from "@/lib/api/client";

import { AssetPanel } from "./AssetPanel";
import { DropZone } from "./DropZone";

vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

const ASSET: AssetOut = {
  id: "a1",
  case_id: "c1",
  original_filename: "C.jpg",
  content_type: "image/jpeg",
  width: 2048,
  height: 1365,
  byte_size: 137_886,
  created_at: "2026-11-10T21:00:00Z",
  fingerprints: { sha256: "ab".repeat(32), phash: "f".repeat(16), dhash: "e".repeat(16), pdq: "c".repeat(64), pdq_quality: 100 },
  metadata: {
    status: "ok",
    tool: "exiftool",
    tool_version: "13.62",
    tag_count: 42,
    error: null,
    summary: {
      capture_time: { stated: "2021:03:04 05:06:07", tag: "ExifIFD:DateTimeOriginal", utc: null },
      camera_make: "Canon",
      camera_model: "EOS R5",
      software: null,
      gps_latitude: 51.5,
      gps_longitude: -0.125,
      credit: null,
      copyright: null,
      groups: ["ExifIFD", "IFD0"],
    },
  },
  credentials: {
    state: "present_untrusted",
    trust_list: "c2pa-trust-list@64b3f9c",
    validation_state: "Valid",
    failures: ["signingCredential.untrusted"],
    signer_issuer: "C2PA Test Signing Cert",
    signer_common_name: "C2PA Signer",
    signed_at: "2023-09-29T17:40:14Z",
    claim_generator: "make_test_images/0.33.1",
    title: "C.jpg",
    actions: ["c2pa.opened"],
    error: null,
  },
  embedding: { status: "pending", model: null },
  display_url: "/assets/a1/display",
  runs: [],
};

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("AssetPanel", () => {
  it("shows fingerprints, credentials and metadata without overstating them", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(JSON.stringify(ASSET), { status: 200, headers: { "content-type": "application/json" } })),
    );
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <AssetPanel assetId="a1" />
      </QueryClientProvider>,
    );

    expect(await screen.findByText("Signed, signer not trusted")).toBeTruthy();
    expect(screen.getByText("ab".repeat(32))).toBeTruthy();
    expect(screen.getByText("2023-09-29 17:40:14Z")).toBeTruthy();
    // A capture time without a zone is shown as stated, never converted.
    expect(screen.getByText(/2021:03:04 05:06:07, zone not stated/)).toBeTruthy();
    expect(screen.getByText("51.500000, -0.125000")).toBeTruthy();
    expect(screen.getByText(/pending: computed by the first trace/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Start trace" })).toBeTruthy();
    expect(screen.getByRole("img").getAttribute("src")).toContain("/assets/a1/display");
  });
});

describe("DropZone", () => {
  it("hands the chosen file over once", () => {
    const onFile = vi.fn();
    render(<DropZone onFile={onFile} />);
    const input = screen.getByLabelText("Choose a file") as HTMLInputElement;
    const file = new File(["x"], "x.jpg", { type: "image/jpeg" });
    fireEvent.change(input, { target: { files: [file] } });
    expect(onFile).toHaveBeenCalledWith(file);
  });

  it("does not accept files while busy", () => {
    const onFile = vi.fn();
    render(<DropZone onFile={onFile} busy />);
    const zone = screen.getByText("Uploading…").parentElement as HTMLElement;
    fireEvent.drop(zone, { dataTransfer: { files: [new File(["x"], "x.jpg")] } });
    expect(onFile).not.toHaveBeenCalled();
  });
});
