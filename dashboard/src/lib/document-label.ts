import type { EditDocument } from "@/api/control-plane";

/** The first non-empty text heading, as the server labels list items (spec 2026-10-18, 3.6). */
export function documentLabel(document: EditDocument): string {
  for (const clip of document.clips ?? []) {
    if (clip.kind === "text" && "heading" in clip && clip.heading.trim()) return clip.heading.trim().slice(0, 120);
  }
  return "Untitled draft";
}
