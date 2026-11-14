/** Backend timestamps are UTC but serialized without a timezone marker. */
function parseUtc(timestamp: string): Date {
  const hasZone = /Z$|[+-]\d\d:?\d\d$/.test(timestamp);
  return new Date(hasZone ? timestamp : `${timestamp}Z`);
}

function formatWhen(timestamp: string): string {
  const d = parseUtc(timestamp);
  const now = new Date();
  const time = d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  if (d.toDateString() === now.toDateString()) return `Today ${time}`;
  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  if (d.toDateString() === yesterday.toDateString()) return `Yesterday ${time}`;
  return `${d.toLocaleDateString([], { month: "short", day: "numeric" })} ${time}`;
}

/** "just now", "12 min ago", "3h ago", then a day and time. */
export function formatAgo(timestamp: string): string {
  const seconds = Math.max(0, (Date.now() - parseUtc(timestamp).getTime()) / 1000);
  if (seconds < 90) return "just now";
  if (seconds < 3600) return `${Math.round(seconds / 60)} min ago`;
  if (seconds < 86400) return `${Math.round(seconds / 3600)}h ago`;
  return formatWhen(timestamp);
}
