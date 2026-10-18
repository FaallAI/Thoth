/** A stored ISO time as the viewer reads it: "Oct 18, 2026, 7:00 AM" in their locale. */
export function formatWhen(iso: string): string {
  return new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}
