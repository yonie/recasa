/** "Sat, 24 Oct 2026" for a trail stop's "2026-10-24", read as a local date. */
export function formatStopDate(dateStr: string): string {
  return new Date(dateStr + "T00:00:00").toLocaleDateString(undefined, {
    weekday: "short",
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}
