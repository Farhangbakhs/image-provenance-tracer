/**
 * Why a run found nothing, when the reason is that no provider could search at all (as opposed
 * to providers searching and finding no copies). Read from the discover stage's notes.
 */
export function searchProblem(
  notes: Record<string, string>,
  candidates: { pending: number; verified: number; unrelated: number; fetch_failed: number },
): string | null {
  const total = candidates.pending + candidates.verified + candidates.unrelated + candidates.fetch_failed;
  if (total > 0) return null;
  const messages = Object.values(notes);
  if (messages.some((m) => m.includes("replay mode: no recording"))) {
    return (
      "Nothing was searched: this stack runs in demo (replay) mode, which only has recorded results for the demo " +
      "images. To trace your own picture, put SERPAPI_API_KEY in .env and start the stack with `make dev`."
    );
  }
  const failed = Object.entries(notes).filter(
    ([name, m]) =>
      name !== "telegram" && (m.startsWith("not queried") || m.startsWith("error") || m.startsWith("skipped")),
  );
  if (messages.some((m) => m.includes("no provider is enabled")) || (failed.length > 0 && failed.length === messages.length)) {
    return "Nothing was searched: no reverse-image provider could run. See the notes below for each provider's reason.";
  }
  return null;
}
