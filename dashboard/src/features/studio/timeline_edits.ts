// Timeline edits as typed operations (spec 2026-11-08 §5.1). Each helper answers the whole batch
// one user action commits, or a refusal the menu shows as its reason; it never edits in place.
import type { EditDocumentOperation, EditDocumentV2 } from "@/api/control-plane";
import { compatibleTrackIds } from "./timeline_domain";

export type Refusal = "locked" | "later_locked" | "crossing" | "scene" | "outside" | "no_gap" | "not_empty" | "edge" | "incompatible";
export type Edit = { operations: EditDocumentOperation[]; refusal?: Refusal };

type Clip = NonNullable<EditDocumentV2["clips"]>[number];

const newId = (prefix: string) => `${prefix}_${crypto.randomUUID()}`;
const refuse = (refusal: Refusal): Edit => ({ operations: [], refusal });
const none: Edit = { operations: [] };

const clipsOf = (doc: EditDocumentV2) => doc.clips ?? [];
const trackOf = (doc: EditDocumentV2, trackId: string) => doc.tracks.find((track) => track.track_id === trackId);
const endOf = (clip: Clip) => clip.from_frame + clip.duration_in_frames;
const isLocked = (doc: EditDocumentV2, clip: Clip) => clip.locked === true || trackOf(doc, clip.track_id)?.locked === true;

/** Move every clip at or after `from`, on every track, left by `length` (operator, 2026-11-08: tracks stay in sync). */
function pullLeft(doc: EditDocumentV2, clips: Clip[], from: number, length: number): EditDocumentOperation[] {
  const order = (clip: Clip) => trackOf(doc, clip.track_id)?.order ?? 0;
  return clips
    .filter((clip) => clip.from_frame >= from)
    .sort((left, right) => order(left) - order(right) || left.from_frame - right.from_frame)
    .map((clip) => ({
      kind: "move_clip",
      operation_id: newId("op"),
      clip_id: clip.clip_id,
      target_track_id: clip.track_id,
      from_frame: clip.from_frame - length,
      ripple: false,
    }));
}

/**
 * A clip on another track that covers the whole stretch [start, end) and outlasts it: a heading or a
 * music bed. It shortens by the stretch's length instead of blocking the edit (operator, 2026-11-08).
 */
const spans = (clip: Clip, start: number, end: number) =>
  clip.from_frame <= start && endOf(clip) >= end && clip.duration_in_frames > end - start;

/** Refusal for pulling `others` left over the stretch [start, end), or nothing when it may. */
function blocked(doc: EditDocumentV2, others: Clip[], start: number, end: number): Refusal | undefined {
  const inside = others.filter((clip) => clip.from_frame < end && endOf(clip) > start);
  if (inside.some((clip) => !spans(clip, start, end))) return "crossing";
  const later = others.filter((clip) => clip.from_frame >= end);
  if ([...inside, ...later].some((clip) => isLocked(doc, clip))) return "later_locked";
  // The server keeps a scene-bound clip inside its scene; a pull that leaves it would be refused on save.
  const length = end - start;
  const leaves = (clip: Clip) => {
    const scene = clip.scene_id ? doc.scenes.find((entry) => entry.scene_id === clip.scene_id) : undefined;
    return Boolean(scene) && clip.from_frame - length < scene!.start_frame;
  };
  if (later.some(leaves)) return "scene";
  return undefined;
}

/** Shorten every clip that spans [start, end) by the stretch's length. */
function shorten(others: Clip[], start: number, end: number): EditDocumentOperation[] {
  return others
    .filter((clip) => clip.from_frame < end && endOf(clip) > start && spans(clip, start, end))
    .map((clip) => ({
      kind: "trim_clip_end",
      operation_id: newId("op"),
      clip_id: clip.clip_id,
      end_frame: endOf(clip) - (end - start),
    }));
}

export function deleteClip(doc: EditDocumentV2, clipId: string): Edit {
  const clip = clipsOf(doc).find((entry) => entry.clip_id === clipId);
  if (!clip) return none;
  if (isLocked(doc, clip)) return refuse("locked");
  return { operations: [{ kind: "remove_clip", operation_id: newId("op"), clip_id: clipId }] };
}

export function rippleDelete(doc: EditDocumentV2, clipId: string): Edit {
  const clip = clipsOf(doc).find((entry) => entry.clip_id === clipId);
  if (!clip) return none;
  if (isLocked(doc, clip)) return refuse("locked");
  const others = clipsOf(doc).filter((entry) => entry.clip_id !== clipId);
  const refusal = blocked(doc, others, clip.from_frame, endOf(clip));
  if (refusal) return refuse(refusal);
  return {
    operations: [
      { kind: "remove_clip", operation_id: newId("op"), clip_id: clipId },
      ...shorten(others, clip.from_frame, endOf(clip)),
      ...pullLeft(doc, others, endOf(clip), clip.duration_in_frames),
    ],
  };
}

export function splitAt(doc: EditDocumentV2, clipId: string, frame: number): Edit {
  const clip = clipsOf(doc).find((entry) => entry.clip_id === clipId);
  if (!clip) return none;
  if (isLocked(doc, clip)) return refuse("locked");
  if (frame <= clip.from_frame || frame >= endOf(clip)) return refuse("outside");
  return {
    operations: [
      {
        kind: "split_clip",
        operation_id: newId("op"),
        clip_id: clipId,
        split_frame: frame,
        left_clip_id: newId("clip"),
        right_clip_id: newId("clip"),
      },
    ],
  };
}

export function moveToTrack(doc: EditDocumentV2, clipId: string, trackId: string): Edit {
  const clip = clipsOf(doc).find((entry) => entry.clip_id === clipId);
  if (!clip) return none;
  if (isLocked(doc, clip)) return refuse("locked");
  if (trackId === clip.track_id || !compatibleTrackIds(doc, clip.kind).includes(trackId)) return refuse("incompatible");
  return {
    operations: [
      {
        kind: "move_clip",
        operation_id: newId("op"),
        clip_id: clipId,
        target_track_id: trackId,
        from_frame: clip.from_frame,
        ripple: false,
      },
    ],
  };
}

/** The empty stretch around `frame` between two clips of one track; none before the first or after the last. */
export function gapAt(doc: EditDocumentV2, trackId: string, frame: number): { start: number; end: number } | null {
  const clips = clipsOf(doc)
    .filter((clip) => clip.track_id === trackId)
    .sort((left, right) => left.from_frame - right.from_frame);
  for (let index = 1; index < clips.length; index += 1) {
    const start = endOf(clips[index - 1]!);
    const end = clips[index]!.from_frame;
    if (start < end && frame >= start && frame < end) return { start, end };
  }
  return null;
}

export function closeGap(doc: EditDocumentV2, trackId: string, frame: number): Edit {
  const gap = gapAt(doc, trackId, frame);
  if (!gap) return refuse("no_gap");
  // The gap's own track holds nothing inside it, so every clip can be checked at once.
  const refusal = blocked(doc, clipsOf(doc), gap.start, gap.end);
  if (refusal) return refuse(refusal);
  return {
    operations: [
      ...shorten(clipsOf(doc), gap.start, gap.end),
      ...pullLeft(doc, clipsOf(doc), gap.end, gap.end - gap.start),
    ],
  };
}

export function moveTrack(doc: EditDocumentV2, trackId: string, direction: -1 | 1): Edit {
  const tracks = [...doc.tracks].sort((left, right) => left.order - right.order);
  const index = tracks.findIndex((track) => track.track_id === trackId);
  const track = tracks[index];
  const neighbour = tracks[index + direction];
  if (!track) return none;
  if (!neighbour) return refuse("edge");
  if (track.locked || neighbour.locked) return refuse("locked");
  return {
    operations: [
      { kind: "reorder_track", operation_id: newId("op"), track_id: track.track_id, order: neighbour.order },
      { kind: "reorder_track", operation_id: newId("op"), track_id: neighbour.track_id, order: track.order },
    ],
  };
}

export function removeTrack(doc: EditDocumentV2, trackId: string): Edit {
  const track = trackOf(doc, trackId);
  if (!track) return none;
  if (track.locked) return refuse("locked");
  if (track.clip_ids?.length) return refuse("not_empty");
  return { operations: [{ kind: "remove_empty_track", operation_id: newId("op"), track_id: trackId }] };
}

/** Hide or lock a clip; unlocking stays possible on a locked clip, as the server allows. */
export function setClipFlag(doc: EditDocumentV2, clipId: string, flag: "hidden" | "locked", value: boolean): Edit {
  const clip = clipsOf(doc).find((entry) => entry.clip_id === clipId);
  if (!clip) return none;
  if (flag === "hidden") {
    if (isLocked(doc, clip)) return refuse("locked");
    return { operations: [{ kind: "set_clip_hidden", operation_id: newId("op"), clip_id: clipId, hidden: value }] };
  }
  return { operations: [{ kind: "set_clip_locked", operation_id: newId("op"), clip_id: clipId, locked: value }] };
}
