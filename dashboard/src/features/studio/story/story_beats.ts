/**
 * Story mode's beats (spec 2026-10-27 §4), computed from the draft and never stored.
 *
 * A clip's beat comes from its `source_role`; a clip saved before Story mode is found
 * through the inventory item its id names (`clip_<item_id>`); any other clip takes the
 * beat of its scene. Only `source_role` ever names Hook or Outro.
 */

import type { EditDocumentV2, StudioImportItem } from "@/api/control-plane";

type Clip = NonNullable<EditDocumentV2["clips"]>[number];
export type StoryRole = NonNullable<Clip["source_role"]>;
export type BeatId = "hook" | "main" | "evidence" | "reactions" | "footage" | "outro";
export type Beat = {
  id: BeatId;
  clipIds: string[];
  startFrame: number;
  durationInFrames: number;
  missing: StudioImportItem[];
};

export const BEAT_ORDER: readonly BeatId[] = ["hook", "main", "evidence", "reactions", "footage", "outro"];

export const ROLE_BEAT: Record<StoryRole, BeatId> = {
  main: "main",
  main_footage: "main",
  slide: "main",
  post_card: "evidence",
  profile_card: "evidence",
  profile_page: "evidence",
  comment_card: "reactions",
  comment: "reactions",
  footage: "footage",
  creator_footage: "footage",
  creator_photo: "footage",
  hook: "hook",
  outro: "outro",
};

function ownRole(clip: Clip, items: Map<string, StudioImportItem>): StoryRole | null {
  if (clip.source_role) return clip.source_role;
  const role = items.get(clip.clip_id.replace(/^clip_/, ""))?.role;
  // The inventory never names Hook or Outro, so a fallback cannot either.
  return role ?? null;
}

function beats(document: EditDocumentV2, inventory: StudioImportItem[]): Map<string, BeatId> {
  const items = new Map(inventory.map((entry) => [entry.item_id, entry]));
  const clips = document.clips ?? [];
  const kindOf = new Map(document.tracks.map((track) => [track.track_id, track.kind]));
  const result = new Map<string, BeatId>();
  for (const clip of clips) {
    const role = ownRole(clip, items);
    if (role) result.set(clip.clip_id, ROLE_BEAT[role]);
  }
  // A scene's other clips (its title, a quoted comment) follow the scene's main clip.
  const sceneBeat = new Map<string, BeatId>();
  const ranked = [...clips].sort(
    (a, b) => Number(kindOf.get(b.track_id) === "main_video") - Number(kindOf.get(a.track_id) === "main_video"),
  );
  for (const clip of ranked) {
    const beat = result.get(clip.clip_id);
    if (clip.scene_id && beat && beat !== "hook" && beat !== "outro" && !sceneBeat.has(clip.scene_id)) {
      sceneBeat.set(clip.scene_id, beat);
    }
  }
  for (const clip of clips) {
    const beat = clip.scene_id ? sceneBeat.get(clip.scene_id) : undefined;
    if (!result.has(clip.clip_id) && beat) result.set(clip.clip_id, beat);
  }
  return result;
}

export function beatOfClip(document: EditDocumentV2, inventory: StudioImportItem[], clipId: string): BeatId | null {
  return beats(document, inventory).get(clipId) ?? null;
}

export function computeBeats(document: EditDocumentV2, inventory: StudioImportItem[]): Beat[] {
  const of = beats(document, inventory);
  const grouped = new Map<BeatId, Clip[]>();
  for (const clip of document.clips ?? []) {
    const beat = of.get(clip.clip_id);
    if (!beat || clip.hidden) continue;
    grouped.set(beat, [...(grouped.get(beat) ?? []), clip]);
  }
  const result: Beat[] = [...grouped].map(([id, clips]) => {
    const ordered = [...clips].sort((a, b) => a.from_frame - b.from_frame);
    const start = ordered[0]!.from_frame;
    const end = Math.max(...ordered.map((clip) => clip.from_frame + clip.duration_in_frames));
    return {
      id,
      clipIds: ordered.map((clip) => clip.clip_id),
      startFrame: start,
      durationInFrames: end - start,
      missing: inventory.filter(
        (entry) =>
          entry.disposition === "unresolved" && entry.media_kind !== "none" && entry.role && ROLE_BEAT[entry.role] === id,
      ),
    };
  });
  // A beat whose material is missing and that has no clip still shows, so the gap is seen.
  for (const entry of inventory) {
    const id = entry.role ? ROLE_BEAT[entry.role] : undefined;
    if (!id || entry.disposition !== "unresolved" || entry.media_kind === "none" || grouped.has(id)) continue;
    const empty = result.find((beat) => beat.id === id);
    if (empty) empty.missing.push(entry);
    else result.push({ id, clipIds: [], startFrame: 0, durationInFrames: 0, missing: [entry] });
  }
  return result.sort((a, b) => a.startFrame - b.startFrame || BEAT_ORDER.indexOf(a.id) - BEAT_ORDER.indexOf(b.id));
}
