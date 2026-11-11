import { describe, expect, it } from "vitest";

import { searchProblem } from "./search-problem";

const none = { pending: 0, verified: 0, unrelated: 0, fetch_failed: 0 };

describe("searchProblem", () => {
  it("explains replay mode when the demo has no recording for an upload", () => {
    const why = searchProblem({ lens: "error: replay mode: no recording for provider 'lens' and image 3b8c" }, none);
    expect(why).toMatch(/demo \(replay\) mode/);
  });

  it("says nothing was searched when every provider failed or was not queried", () => {
    expect(
      searchProblem(
        { vision: "not queried: GOOGLE_VISION_API_KEY is not set", lens: "skipped_quota: monthly limit reached" },
        none,
      ),
    ).toMatch(/no reverse-image provider could run/);
  });

  it("stays quiet when providers searched, even if one failed or nothing was found", () => {
    expect(searchProblem({}, none)).toBeNull();
    expect(searchProblem({ vision: "not queried: no key" }, { ...none, unrelated: 2 })).toBeNull();
  });
});
