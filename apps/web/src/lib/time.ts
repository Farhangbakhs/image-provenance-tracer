/**
 * All times in ORIGIN are shown in UTC, ISO-like, with a trailing "Z" so the zone is
 * never ambiguous. Precision drops to the date when the value is only known to the day.
 */
export function formatUtc(value: string | Date, precision: "second" | "minute" | "day" = "minute"): string {
  const date = typeof value === "string" ? new Date(value) : value;
  if (Number.isNaN(date.getTime())) {
    throw new RangeError(`Invalid date: ${String(value)}`);
  }
  const iso = date.toISOString(); // always UTC: YYYY-MM-DDTHH:mm:ss.sssZ
  const day = iso.slice(0, 10);
  if (precision === "day") return day;
  const clock = precision === "second" ? iso.slice(11, 19) : iso.slice(11, 16);
  return `${day} ${clock}Z`;
}
