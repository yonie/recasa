/** Display formatting shared across pages. */

export function formatBytes(bytes: number): string {
  if (bytes === 0) return "0 B";
  const k = 1024;
  const sizes = ["B", "KB", "MB", "GB", "TB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(1))} ${sizes[i]}`;
}

/** "1:05" for a video duration in seconds; empty when unknown. */
export function formatDuration(seconds: number | null): string {
  if (!seconds || seconds < 0) return "";
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

/** The noun for a count: plural(1, "photo") is "photo", plural(2, "photo") "photos". */
export function plural(count: number, singular: string, pluralForm = `${singular}s`): string {
  return count === 1 ? singular : pluralForm;
}

/**
 * Heading for a timeline group key: "2024", "2024-03" (month) or
 * "2024-03-15" (day), or "unknown" for photos without any date.
 */
export function formatGroupDate(key: string): string {
  if (key === "unknown") return "Unknown Date";
  const parts = key.split("-");
  if (parts.length === 1) return parts[0]!;
  if (parts.length === 2) {
    const date = new Date(parseInt(parts[0]!), parseInt(parts[1]!) - 1);
    return date.toLocaleDateString(undefined, { year: "numeric", month: "long" });
  }
  return new Date(key).toLocaleDateString(undefined, {
    year: "numeric",
    month: "long",
    day: "numeric",
  });
}

/** Just the month name of a "2024-03" group key, for groups inside one year. */
export function formatMonthName(key: string): string {
  const parts = key.split("-");
  if (parts.length < 2) return key;
  const date = new Date(parseInt(parts[0]!), parseInt(parts[1]!) - 1);
  return date.toLocaleDateString(undefined, { month: "long" });
}
