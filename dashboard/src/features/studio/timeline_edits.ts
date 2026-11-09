// Timeline edits as typed operations (spec 2026-11-08 §5.1). Each helper answers the whole batch
// one user action commits, or a refusal the menu shows as its reason; it never edits in place.
import type { EditDocumentOperation, EditDocumentV2 } from "@/api/control-plane";
import { applyTimelineOperation, compatibleTrackIds, sourceSpan, speedPercent } from "./timeline_domain";

export type Refusal =
  | "locked"
  | "later_locked"
  | "crossing"
  | "scene"
  | "outside"
  | "no_gap"
  | "not_empty"
  | "edge"
  | "incompatible"
  | "no_room"
  | "gone"
  | "no_track"
  | "no_scene"
  | "not_text"
  | "not_caption"
  | "too_long"
  | "no_source"
  | "still"
  | "not_touching"
  | "scene_cut"
  | "taken"
  | "too_many"
  | "whole_source"
  | "no_footage";
/** Something a successful edit still tells the person (operator, 2026-11-09). */
export type Notice = "hidden_track";
export type Edit = { operations: EditDocumentOperation[]; refusal?: Refusal; notice?: Notice };

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

// --------------------------------------------------------------------------
// The whole selection (spec 2026-11-08 §6): one batch for every clip, or a refusal for all.
// --------------------------------------------------------------------------

const picked = (doc: EditDocumentV2, ids: readonly string[]) => clipsOf(doc).filter((clip) => ids.includes(clip.clip_id));

/** Apply a batch on a working copy, the way `commit_operations` will. */
const applied = (doc: EditDocumentV2, operations: EditDocumentOperation[]) =>
  operations.reduce((current, operation) => applyTimelineOperation(current, operation, {}), doc);

export function deleteClips(doc: EditDocumentV2, ids: readonly string[]): Edit {
  const clips = picked(doc, ids);
  if (clips.some((clip) => isLocked(doc, clip))) return refuse("locked");
  return { operations: clips.map((clip) => ({ kind: "remove_clip", operation_id: newId("op"), clip_id: clip.clip_id })) };
}

/** Ripple each clip out, the latest first, on the document the earlier removals left. */
export function rippleDeleteClips(doc: EditDocumentV2, ids: readonly string[]): Edit {
  const order = picked(doc, ids).sort((left, right) => right.from_frame - left.from_frame);
  const operations: EditDocumentOperation[] = [];
  let current = doc;
  for (const clip of order) {
    const edit = rippleDelete(current, clip.clip_id);
    if (edit.refusal) return refuse(edit.refusal);
    operations.push(...edit.operations);
    current = applied(current, edit.operations);
  }
  return { operations };
}

export function setClipsFlag(doc: EditDocumentV2, ids: readonly string[], flag: "hidden" | "locked", value: boolean): Edit {
  const edits = picked(doc, ids).map((clip) => setClipFlag(doc, clip.clip_id, flag, value));
  const refused = edits.find((edit) => edit.refusal);
  return refused ? refuse(refused.refusal!) : { operations: edits.flatMap((edit) => edit.operations) };
}

/** Every clip by the same frames on its own track; nothing leaves the canvas. */
export function moveClips(doc: EditDocumentV2, ids: readonly string[], delta: number): Edit {
  const clips = picked(doc, ids);
  if (clips.some((clip) => isLocked(doc, clip))) return refuse("locked");
  const canvas = doc.canvas.duration_in_frames;
  if (clips.some((clip) => clip.from_frame + delta < 0 || endOf(clip) + delta > canvas)) return refuse("outside");
  // The server keeps each clip inside its scene and Main video clips apart (carried minors, 2026-11-09).
  const sceneOf = (clip: Clip) => (clip.scene_id ? doc.scenes.find((scene) => scene.scene_id === clip.scene_id) : undefined);
  const leaves = (clip: Clip) => {
    const scene = sceneOf(clip);
    return scene !== undefined && (clip.from_frame + delta < scene.start_frame || endOf(clip) + delta > scene.start_frame + scene.duration_in_frames);
  };
  if (clips.some(leaves)) return refuse("scene");
  const moving = new Set(clips.map((clip) => clip.clip_id));
  const stays = clipsOf(doc).filter((clip) => !moving.has(clip.clip_id));
  const collides = (clip: Clip) =>
    trackOf(doc, clip.track_id)?.kind === "main_video" &&
    stays.some((other) => other.track_id === clip.track_id && other.from_frame < endOf(clip) + delta && endOf(other) > clip.from_frame + delta);
  if (clips.some(collides)) return refuse("no_room");
  return {
    operations: clips.map((clip) => ({
      kind: "move_clip",
      operation_id: newId("op"),
      clip_id: clip.clip_id,
      target_track_id: clip.track_id,
      from_frame: clip.from_frame + delta,
      ripple: false,
    })),
  };
}

// --------------------------------------------------------------------------
// Copies inside the open draft (spec 2026-11-08 §6); the system clipboard never carries clips.
// --------------------------------------------------------------------------

/**
 * `duplicate_clip` for each clip, placed at `at` on its own track with its offset from the earliest.
 * A copy names a live clip only, so its media and provenance come from the draft, never from outside.
 */
export function pasteClips(doc: EditDocumentV2, ids: readonly string[], at: number): Edit {
  const clips = picked(doc, ids).sort((left, right) => left.from_frame - right.from_frame);
  if (clips.length !== new Set(ids).size) return refuse("gone");
  if (!clips.length) return none;
  const earliest = clips[0]!.from_frame;
  const placed = clips.map((clip) => ({ clip, from: at + clip.from_frame - earliest }));
  if (placed.some(({ clip, from }) => from < 0 || from + clip.duration_in_frames > doc.canvas.duration_in_frames)) {
    return refuse("outside");
  }
  if (placed.some(({ clip }) => trackOf(doc, clip.track_id)?.locked)) return refuse("locked");
  // The server keeps Main video clips from overlapping, existing ones and the copies alike.
  // Per track, as the server checks it (carried minor, 2026-11-09).
  const main = (clip: Clip) => trackOf(doc, clip.track_id)?.kind === "main_video";
  const taken = clipsOf(doc).filter(main).map((clip) => [clip.track_id, clip.from_frame, endOf(clip)] as const);
  for (const { clip, from } of placed.filter(({ clip }) => main(clip))) {
    const end = from + clip.duration_in_frames;
    if (taken.some(([track, start, stop]) => track === clip.track_id && start < end && stop > from)) return refuse("no_room");
    taken.push([clip.track_id, from, end]);
  }
  return {
    operations: placed.map(({ clip, from }) => ({
      kind: "duplicate_clip",
      operation_id: newId("op"),
      clip_id: clip.clip_id,
      new_clip_id: newId("clip"),
      track_id: clip.track_id,
      from_frame: from,
    })),
  };
}

/** The selection again, right after its own end. */
export function duplicateClips(doc: EditDocumentV2, ids: readonly string[]): Edit {
  const clips = picked(doc, ids);
  if (!clips.length) return none;
  return pasteClips(doc, ids, Math.max(...clips.map(endOf)));
}

// --------------------------------------------------------------------------
// Pasted text, to the place the person picks (spec 2026-11-08 §6)
// --------------------------------------------------------------------------

export type PasteTarget = "new_text" | "replace_text" | "new_caption" | "replace_caption";
export const PASTE_TARGETS: readonly PasteTarget[] = ["new_text", "replace_text", "new_caption", "replace_caption"];

/** A heading and a caption cue hold at most this many characters (`ShortText`). */
export const TEXT_LIMIT = 300;
/** A pasted text clip lasts three seconds, cut at the canvas end. */
const PASTED_TEXT_SECONDS = 3;

/** The caption cue under `frame`, or the first one. */
export function cueAt(clip: Extract<Clip, { kind: "caption" }>, frame: number): number {
  const offset = frame - clip.from_frame;
  const index = clip.cues.findIndex((cue) => cue.from_frame <= offset && offset < cue.from_frame + cue.duration_in_frames);
  return Math.max(0, index);
}

/** An unlocked track of the kind, a visible one first: a hidden one still takes the text (operator, 2026-11-09). */
function pasteTrack(doc: EditDocumentV2, kind: "overlay" | "caption") {
  const open = doc.tracks.filter((entry) => entry.kind === kind && !entry.locked);
  return open.find((entry) => !entry.hidden) ?? open[0];
}

export function pasteTextOperations(
  doc: EditDocumentV2,
  target: PasteTarget,
  text: string,
  at: { playheadFrame: number; selectedClipId: string },
): Edit {
  if (text.length > TEXT_LIMIT) return refuse("too_long");
  const selected = clipsOf(doc).find((clip) => clip.clip_id === at.selectedClipId);
  const frame = at.playheadFrame;
  switch (target) {
    case "new_text": {
      const track = pasteTrack(doc, "overlay");
      if (!track) return refuse("no_track");
      return {
        operations: [
          {
            kind: "add_text_clip",
            operation_id: newId("op"),
            clip_id: newId("clip"),
            track_id: track.track_id,
            from_frame: frame,
            duration_in_frames: Math.min(Math.round(PASTED_TEXT_SECONDS * doc.canvas.fps), doc.canvas.duration_in_frames - frame),
            heading: text,
            body: "",
            style_slot: "title",
          },
        ],
        ...(track.hidden ? { notice: "hidden_track" as const } : {}),
      };
    }
    case "replace_text":
      if (selected?.kind !== "text") return refuse("not_text");
      if (isLocked(doc, selected)) return refuse("locked");
      return { operations: [{ kind: "replace_text", operation_id: newId("op"), clip_id: selected.clip_id, field: "heading", value: text }] };
    case "new_caption": {
      const track = pasteTrack(doc, "caption");
      if (!track) return refuse("no_track");
      const scene = doc.scenes.find((entry) => entry.start_frame <= frame && frame < entry.start_frame + entry.duration_in_frames);
      if (!scene) return refuse("no_scene");
      return {
        operations: [
          { kind: "add_caption_clip", operation_id: newId("op"), clip_id: newId("clip"), track_id: track.track_id, scene_id: scene.scene_id, text },
        ],
        ...(track.hidden ? { notice: "hidden_track" as const } : {}),
      };
    }
    case "replace_caption":
      if (selected?.kind !== "caption") return refuse("not_caption");
      if (isLocked(doc, selected)) return refuse("locked");
      return {
        operations: [
          { kind: "set_caption_cue_text", operation_id: newId("op"), clip_id: selected.clip_id, cue_index: cueAt(selected, frame), text },
        ],
      };
  }
}

// --------------------------------------------------------------------------
// Every gap at once (spec 2026-11-08 §6)
// --------------------------------------------------------------------------

/** The first stretch between two clips of one track, or none. */
function firstGap(doc: EditDocumentV2, trackId: string): { start: number; end: number } | null {
  const clips = clipsOf(doc)
    .filter((clip) => clip.track_id === trackId)
    .sort((left, right) => left.from_frame - right.from_frame);
  for (let index = 1; index < clips.length; index += 1) {
    // The same stretch gapAt finds, so closeGap closes exactly this one.
    const start = endOf(clips[index - 1]!);
    if (start < clips[index]!.from_frame) return { start, end: clips[index]!.from_frame };
  }
  return null;
}

/** Each gap of one track closed left to right on the evolving document, as "Close this gap" would. */
export function closeAllGaps(doc: EditDocumentV2, trackId: string): Edit {
  const operations: EditDocumentOperation[] = [];
  let current = doc;
  // ponytail: one pass per gap; a track holds far fewer gaps than this cap.
  for (let pass = 0; pass < 500; pass += 1) {
    const gap = firstGap(current, trackId);
    if (!gap) break;
    const edit = closeGap(current, trackId, gap.start);
    if (edit.refusal) return refuse(edit.refusal);
    operations.push(...edit.operations);
    current = applied(current, edit.operations);
  }
  return operations.length ? { operations } : refuse("no_gap");
}

/** Every stretch between the first clip and the last where no track holds a clip, closed in one batch. */
export function closeTimelineGaps(doc: EditDocumentV2): Edit {
  const spans = clipsOf(doc)
    .map((clip) => [clip.from_frame, endOf(clip)] as const)
    .sort((left, right) => left[0] - right[0]);
  const gaps: { start: number; end: number }[] = [];
  let reach = spans[0]?.[1] ?? 0;
  for (const [from, to] of spans.slice(1)) {
    if (from > reach) gaps.push({ start: reach, end: from });
    reach = Math.max(reach, to);
  }
  if (!gaps.length) return refuse("no_gap");
  const operations: EditDocumentOperation[] = [];
  let current = doc;
  // Right to left, so each stretch is still where it was found when its turn comes.
  for (const gap of gaps.reverse()) {
    const refusal = blocked(current, clipsOf(current), gap.start, gap.end);
    if (refusal) return refuse(refusal);
    const moves = pullLeft(current, clipsOf(current), gap.end, gap.end - gap.start);
    operations.push(...moves);
    current = applied(current, moves);
  }
  return { operations };
}

// --------------------------------------------------------------------------
// Slip (Tier 3a): the content moves inside the clip; the clip keeps its place
// --------------------------------------------------------------------------

/** The source starts a clip may take: 0 up to where its span still fits, or null when it has no source time. */
export function slipRange(doc: EditDocumentV2, clip: Clip): { max: number } | Refusal {
  if (clip.kind !== "video" && clip.kind !== "audio") return "still";
  const asset = doc.asset_refs?.find((ref) => ref.asset_id === clip.asset_id);
  if (asset?.kind === "image") return "still";
  const length = asset?.duration_in_frames;
  if (length == null) return { max: Number.POSITIVE_INFINITY };
  // A clip that holds its last frame may start anywhere inside its source.
  const max = clip.kind === "video" && clip.hold_after_source ? length - 1 : length - sourceSpan(clip);
  return max > 0 ? { max } : "whole_source";
}

/** Slip a clip so its source starts at `sourceFrom`, clamped to what the source holds. */
export function slipClip(doc: EditDocumentV2, clipId: string, sourceFrom: number): Edit {
  const clip = clipsOf(doc).find((entry) => entry.clip_id === clipId);
  if (!clip) return refuse("gone");
  if (isLocked(doc, clip)) return refuse("locked");
  const range = slipRange(doc, clip);
  if (typeof range === "string") return refuse(range);
  const start = Math.min(range.max, Math.max(0, Math.round(sourceFrom)));
  if (!("source_from_frame" in clip) || start === clip.source_from_frame) return none;
  return { operations: [{ kind: "slip_clip", operation_id: newId("op"), clip_id: clip.clip_id, source_from_frame: start }] };
}

// --------------------------------------------------------------------------
// Roll (Tier 3a): the cut between two touching clips moves; their total stays
// --------------------------------------------------------------------------

/** Move the cut where `leftId` ends and `rightId` starts to `frame`: two trims in one patch. */
export function rollCut(doc: EditDocumentV2, leftId: string, rightId: string, frame: number): Edit {
  const left = clipsOf(doc).find((clip) => clip.clip_id === leftId);
  const right = clipsOf(doc).find((clip) => clip.clip_id === rightId);
  if (!left || !right) return refuse("gone");
  if (left.track_id !== right.track_id || endOf(left) !== right.from_frame) return refuse("not_touching");
  if (isLocked(doc, left) || isLocked(doc, right)) return refuse("locked");
  // A clip must stay inside its scene, so a cut between two scenes is not a roll.
  if (left.scene_id && right.scene_id && left.scene_id !== right.scene_id) return refuse("scene_cut");
  if (frame <= left.from_frame || frame >= endOf(right)) return refuse("edge");
  // A copy has no scene, so one side may still have one: that clip stays inside it (final review 2026-11-09).
  const sceneOf = (clip: Clip) => doc.scenes.find((scene) => scene.scene_id === clip.scene_id);
  const leftScene = left.scene_id ? sceneOf(left) : undefined;
  const rightScene = right.scene_id ? sceneOf(right) : undefined;
  if (leftScene && frame > leftScene.start_frame + leftScene.duration_in_frames) return refuse("scene");
  if (rightScene && frame < rightScene.start_frame) return refuse("scene");
  if (frame === right.from_frame) return none;
  // The left clip plays further into its source; the right one starts earlier or later in its own.
  if ("source_from_frame" in left && !(left.kind === "video" && left.hold_after_source)) {
    const length = doc.asset_refs?.find((ref) => ref.asset_id === left.asset_id)?.duration_in_frames;
    const span = sourceSpan({ duration_in_frames: frame - left.from_frame, speed: left.speed });
    if (length != null && left.source_from_frame + span > length) return refuse("no_footage");
  }
  if ("source_from_frame" in right) {
    const moved = Math.floor(((frame - right.from_frame) * speedPercent(right)) / 100);
    if (right.source_from_frame + moved < 0) return refuse("no_footage");
  }
  return {
    operations: [
      { kind: "trim_clip_end", operation_id: newId("op"), clip_id: left.clip_id, end_frame: frame },
      { kind: "trim_clip_start", operation_id: newId("op"), clip_id: right.clip_id, from_frame: frame },
    ],
  };
}

// --------------------------------------------------------------------------
// Markers (Tier 3a)
// --------------------------------------------------------------------------

/** The server keeps at most this many markers on a draft. */
export const MAX_MARKERS = 100;

/** A marker at `frame`, unless one already sits there or the draft holds the most it may. */
export function addMarker(doc: EditDocumentV2, frame: number): Edit {
  const markers = doc.markers ?? [];
  if (markers.some((marker) => marker.frame === frame)) return refuse("taken");
  if (markers.length >= MAX_MARKERS) return refuse("too_many");
  return { operations: [{ kind: "add_marker", operation_id: newId("op"), marker_id: newId("marker"), frame, label: "" }] };
}

/**
 * The frames the cut between two touching clips may move to, or null when no roll is possible.
 * A drag past a limit stops at it, as a slip does (carried minor, 2026-11-09).
 */
export function rollRange(doc: EditDocumentV2, leftId: string, rightId: string): { min: number; max: number } | null {
  const left = clipsOf(doc).find((clip) => clip.clip_id === leftId);
  const right = clipsOf(doc).find((clip) => clip.clip_id === rightId);
  if (!left || !right || left.track_id !== right.track_id || endOf(left) !== right.from_frame) return null;
  let min = left.from_frame + 1;
  let max = endOf(right) - 1;
  const sceneOf = (clip: Clip) => (clip.scene_id ? doc.scenes.find((scene) => scene.scene_id === clip.scene_id) : undefined);
  const leftScene = sceneOf(left);
  const rightScene = sceneOf(right);
  if (leftScene) max = Math.min(max, leftScene.start_frame + leftScene.duration_in_frames);
  if (rightScene) min = Math.max(min, rightScene.start_frame);
  if ("source_from_frame" in left && !(left.kind === "video" && left.hold_after_source)) {
    const length = doc.asset_refs?.find((ref) => ref.asset_id === left.asset_id)?.duration_in_frames;
    if (length != null) max = Math.min(max, left.from_frame + Math.floor(((length - left.source_from_frame) * 100) / speedPercent(left)));
  }
  if ("source_from_frame" in right) {
    min = Math.max(min, right.from_frame - Math.floor((right.source_from_frame * 100) / speedPercent(right)));
  }
  return min <= max ? { min, max } : null;
}
