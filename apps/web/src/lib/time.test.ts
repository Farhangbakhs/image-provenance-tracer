import { describe, expect, it } from "vitest";

import { formatInterval, formatUtc } from "./time";

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

describe("formatInterval", () => {
  it("keeps proven bounds and claims distinct in words", () => {
    expect(formatInterval("2024-03-05T09:00:00Z", "2024-03-05T09:00:00Z")).toBe("2024-03-05 09:00Z");
    expect(formatInterval("2024-03-05T09:00:00Z", "2024-03-06T12:00:00Z")).toBe(
      "between 2024-03-05 09:00Z and 2024-03-06 12:00Z",
    );
    expect(formatInterval(null, "2024-03-06T12:00:00Z")).toBe("no later than 2024-03-06 12:00Z");
    expect(formatInterval("2024-03-01T00:00:00Z", null)).toBe("no earlier than 2024-03-01 00:00Z");
    expect(formatInterval(null, null)).toBe("undated");
  });
});
