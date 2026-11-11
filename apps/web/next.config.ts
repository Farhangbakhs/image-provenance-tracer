import type { NextConfig } from "next";

// A snapshot build is a static, read-only copy of the demo investigations (make snapshot).
const snapshot = process.env.NEXT_PUBLIC_SNAPSHOT === "1";

const nextConfig: NextConfig = {
  // Self-contained server bundle for the container image, or plain files for a static host.
  output: snapshot ? "export" : "standalone",
  // Static hosts serve /runs/<id>/index.html for /runs/<id>/.
  trailingSlash: snapshot,
  // For hosts that serve the site from a sub-path (for example GitHub Pages: /<repo>).
  basePath: process.env.NEXT_PUBLIC_BASE_PATH || undefined,
  // Partial prerendering needs a server, so a static export goes without it.
  cacheComponents: !snapshot,
  partialPrefetching: !snapshot,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
