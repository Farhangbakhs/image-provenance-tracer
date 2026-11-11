/** Shown on every screen and export that presents an earliest date. */
export const EARLIEST_DISCLAIMER = "Earliest found in indexed sources. Earlier copies may exist.";

/** How each kind of dating evidence is named wherever it is shown. */
export const SIGNAL_LABEL: Record<string, string> = {
  observed: "ORIGIN fetched it",
  platform: "platform timestamp",
  c2pa: "Content Credentials signing time",
  wayback_page: "archive capture of the page",
  wayback_image: "archive capture of the image",
  provider_crawl: "date shown by the provider",
  page_metadata: "page's stated date",
  http_last_modified: "server Last-Modified",
  exif: "camera time in the file",
};
