import { readFileSync } from "node:fs";
import { join } from "node:path";

type Kind = "cases" | "assets" | "runs";

/**
 * The ids a static snapshot build pre-renders for a dynamic route, read from the manifest the
 * snapshot export wrote (scripts/snapshot.py). Normal builds render these routes on request;
 * Cache Components still asks for one id at build time, so they get a placeholder whose page
 * is only the loading shell.
 */
export function snapshotParams(kind: Kind): { id: string }[] {
  if (process.env.NEXT_PUBLIC_SNAPSHOT !== "1") return [{ id: "_" }];
  const manifest = JSON.parse(readFileSync(join(process.cwd(), "public", "snapshot", "manifest.json"), "utf-8")) as Record<
    Kind,
    string[]
  >;
  return manifest[kind].map((id) => ({ id }));
}
