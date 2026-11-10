import { describe, expect, it } from "vitest";

import { formatUtc } from "./time";

describe("formatUtc", () => {
  it("renders minutes in UTC with a Z suffix", () => {
    expect(formatUtc("2024-03-05T23:45:10+02:00")).toBe("2024-03-05 21:45Z");
  });

  it("supports second and day precision", () => {
    expect(formatUtc("2024-03-05T21:45:10Z", "second")).toBe("2024-03-05 21:45:10Z");
    expect(formatUtc(new Date(Date.UTC(2024, 2, 5, 23, 59)), "day")).toBe("2024-03-05");
  });

  it("rejects invalid input instead of printing 'Invalid Date'", () => {
    expect(() => formatUtc("not a date")).toThrow(RangeError);
  });
});
