import type { CandidateOut } from "./api/client";

export interface CandidateReading {
  /** One plain sentence: what happened to this hit. */
  headline: string;
  /** The facts behind it, for the details row. */
  facts: { label: string; value: string }[];
}

interface PageInfo {
  status?: number | null;
  final_url?: string | null;
  content_type?: string | null;
  bytes?: number | null;
  redirects?: number | null;
  images_found?: number | null;
  error?: string | null;
}

interface TriedImage {
  url: string;
  result?: string;
  width?: number;
  height?: number;
  sscd?: number;
}

const pageOf = (candidate: CandidateOut): PageInfo =>
  ((candidate.fetch_info as { page?: PageInfo } | null | undefined)?.page ?? {}) as PageInfo;

const imagesOf = (candidate: CandidateOut): TriedImage[] =>
  ((candidate.fetch_info as { images?: TriedImage[] } | null | undefined)?.images ?? []) as TriedImage[];

/** Plain-language reading of a rejected hit, from what verification recorded. */
export function readCandidate(candidate: CandidateOut): CandidateReading {
  const page = pageOf(candidate);
  const tried = imagesOf(candidate);
  const reason = candidate.reason ?? "";
  const facts: { label: string; value: string }[] = [];
  if (page.status != null) facts.push({ label: "Page", value: `HTTP ${page.status}` });
  if (page.final_url) facts.push({ label: "Final URL", value: page.final_url });
  if (page.content_type) facts.push({ label: "Content type", value: page.content_type });
  if (page.bytes != null) facts.push({ label: "Size", value: `${page.bytes.toLocaleString("en-GB")} bytes` });
  if (page.redirects) facts.push({ label: "Redirects", value: String(page.redirects) });
  if (page.images_found != null && page.status === 200) facts.push({ label: "Images found", value: String(page.images_found) });
  if (page.error && page.status == null) facts.push({ label: "Error", value: page.error });

  let headline: string;
  if (candidate.status === "pending") {
    headline = "Not checked: it ranked below the checking limit.";
  } else if (candidate.status === "blocked") {
    headline = "Google's own redirect page answered instead of the publisher's page, so ORIGIN never reached it.";
  } else if (page.status === 401 || page.status === 403 || page.status === 429) {
    headline = `The site refused ORIGIN's request (HTTP ${page.status}), so the page could not be read.`;
  } else if (reason.startsWith("page HTTP")) {
    headline = `The page could not be read (${reason.replace("page ", "")}).`;
  } else if (reason.startsWith("page fetch failed")) {
    headline = "The page could not be fetched.";
  } else if (reason.startsWith("no image on the page")) {
    headline = "The page loaded, but ORIGIN found no image on it to compare.";
  } else if (tried.length > 0) {
    headline = `Compared ${tried.length} image${tried.length === 1 ? "" : "s"} on the page; none matched your picture.`;
  } else {
    headline = reason || "Not matched.";
  }
  return { headline, facts };
}

/** A short, countable reason: the verdict without its numbers. */
export function reasonGroup(reason: string | null | undefined): string {
  const r = reason ?? "";
  if (r.startsWith("SSCD")) return "not the same picture";
  if (r.startsWith("no image on the page")) return "no image on the page";
  if (r.startsWith("blocked by Google redirect")) return "blocked by a Google redirect page";
  if (r.startsWith("page fetch failed")) return "page could not be fetched";
  if (r.startsWith("not a usable image")) return "image not in a usable format";
  return r || "not matched";
}
