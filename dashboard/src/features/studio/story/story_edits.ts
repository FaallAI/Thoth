/**
 * Story mode's edits as plain operation builders (spec 2026-10-27 §5.2, §9). Each returns the
 * revision-bound operations the editor commits as one undo step; none is applied here.
 */

import type { EditDocumentOperation, EditDocumentV2, EditorAsset, StudioImportItem } from "@/api/control-plane";

import type { Beat, StoryRole } from "./story_beats";

type Clip = NonNullable<EditDocumentV2["clips"]>[number];
type Op<K extends EditDocumentOperation["kind"]> = Extract<EditDocumentOperation, { kind: K }>;
export type PositionPreset = "top" | "middle" | "lower";
export type Motion = Op<"set_clip_motion">["motion"];

/** The role a dropped upload, or a material from another group, takes in a beat. */
export const BEAT_ROLE: Partial<Record<Beat["id"], StoryRole>> = {
  main: "main_footage",
  evidence: "post_card",
  reactions: "comment_card",
  footage: "footage",
};

/** Top, Middle and Lower third as stored y offsets (spec §5.2). */
export const PRESET_Y: Record<PositionPreset, number> = { top: -0.24, middle: 0, lower: 0.22 };
// The importer's card layout (python domain/studio_layout.py).
const CARD_WIDTH = 0.76;
const CARD_CENTER_Y = 0.26;
const READING_CPS = 15;

const id = () => `op_${crypto.randomUUID()}`;
const clipOf = (document: EditDocumentV2, clipId: string) =>
  (document.clips ?? []).find((clip) => clip.clip_id === clipId);
const positionOf = (clip: Clip | undefined) =>
  (clip && "position" in clip && clip.position) || { x: 0, y: 0, scale: 1 };

export function setPositionPreset(document: EditDocumentV2, clipIds: string[], preset: PositionPreset): Op<"set_clip_position">[] {
  return clipIds.map((clipId) => ({
    kind: "set_clip_position",
    operation_id: id(),
    clip_id: clipId,
    position: { ...positionOf(clipOf(document, clipId)), y: PRESET_Y[preset] },
  }));
}

export const setMotion = (clipIds: string[], motion: Motion): Op<"set_clip_motion">[] =>
  clipIds.map((clipId) => ({ kind: "set_clip_motion", operation_id: id(), clip_id: clipId, motion }));

export const setEmphasis = (clipIds: string[], highlight: boolean, arrow: boolean): Op<"set_clip_emphasis">[] =>
  clipIds.map((clipId) => ({ kind: "set_clip_emphasis", operation_id: id(), clip_id: clipId, highlight, arrow }));

export const removeFromBeat = (clipId: string): Op<"set_clip_hidden"> => ({
  kind: "set_clip_hidden",
  operation_id: id(),
  clip_id: clipId,
  hidden: true,
});

/**
 * Two clips trade places. Clips of two scenes trade their scenes (the scene strip stays
 * contiguous); otherwise the later clip takes the earlier start and the earlier one ends
 * where the later one ended, so the pair's span, and its scene, are unchanged.
 */
export function swapClips(document: EditDocumentV2, firstId: string, secondId: string): EditDocumentOperation[] {
  const [a, b] = [clipOf(document, firstId), clipOf(document, secondId)].sort(
    (x, y) => (x?.from_frame ?? 0) - (y?.from_frame ?? 0),
  );
  if (!a || !b) return [];
  if (a.scene_id && b.scene_id && a.scene_id !== b.scene_id) {
    const index = document.scenes.findIndex((scene) => scene.scene_id === b.scene_id);
    return [{ kind: "reorder_scene", operation_id: id(), scene_id: a.scene_id, to_index: index }];
  }
  return [
    { kind: "move_clip", operation_id: id(), clip_id: b.clip_id, target_track_id: b.track_id, from_frame: a.from_frame, ripple: false },
    {
      kind: "move_clip",
      operation_id: id(),
      clip_id: a.clip_id,
      target_track_id: a.track_id,
      from_frame: b.from_frame + b.duration_in_frames - a.duration_in_frames,
      ripple: false,
    },
  ];
}

/** Where a clip may end: inside its scene when it has one, else inside the canvas. */
function lastFrame(document: EditDocumentV2, clip: Clip): number {
  const scene = document.scenes.find((entry) => entry.scene_id === clip.scene_id);
  return scene ? scene.start_frame + scene.duration_in_frames : document.canvas.duration_in_frames;
}

export function setClipSeconds(document: EditDocumentV2, clipIds: string[], seconds: number): Op<"trim_clip_end">[] {
  const frames = Math.max(1, Math.round(seconds * document.canvas.fps));
  return clipIds.flatMap((clipId) => {
    const clip = clipOf(document, clipId);
    if (!clip) return [];
    const end = Math.min(clip.from_frame + frames, lastFrame(document, clip));
    return [{ kind: "trim_clip_end", operation_id: id(), clip_id: clipId, end_frame: end }];
  });
}
export const setEachCardSeconds = setClipSeconds;

/** The importer's placement for a contained card, CARD_WIDTH of the canvas wide. */
export function cardPosition(width: number | null | undefined, height: number | null | undefined, canvas: { width: number; height: number }) {
  const drawn = !width || !height ? canvas.width : Math.min(canvas.width, (canvas.height * width) / height);
  return { x: 0, y: CARD_CENTER_Y - 0.5, scale: (CARD_WIDTH * canvas.width) / drawn };
}

/**
 * A material joins its beat right after the beat's last clip, lasting as long as the
 * beat's longest clip. It is bound to no scene, and pulled back inside the canvas.
 */
export function addMaterialToBeat(document: EditDocumentV2, beat: Beat, asset: EditorAsset, role: StoryRole): Op<"add_clip_from_asset"> {
  const fps = document.canvas.fps;
  const lengths = beat.clipIds.map((clipId) => clipOf(document, clipId)?.duration_in_frames ?? 0);
  const duration = Math.min(Math.max(...lengths, 0) || 3 * fps, document.canvas.duration_in_frames);
  const end = beat.startFrame + beat.durationInFrames;
  return {
    kind: "add_clip_from_asset",
    operation_id: id(),
    clip_id: `clip_${crypto.randomUUID().replaceAll("-", "")}`,
    track_id: "track_b_roll",
    asset_id: asset.asset_id,
    from_frame: Math.max(0, Math.min(end, document.canvas.duration_in_frames - duration)),
    duration_in_frames: asset.kind === "video" && asset.duration_in_frames ? Math.min(duration, asset.duration_in_frames) : duration,
    source_from_frame: 0,
    fit: "contain",
    position: cardPosition(asset.width, asset.height, document.canvas),
    source_role: role,
  };
}

/** The longest reading time among the beat's cards, from the import (spec 5c-1 reading speed). */
export function longestReading(beat: Beat, inventory: StudioImportItem[]): number | null {
  const items = new Map(inventory.map((entry) => [`clip_${entry.item_id}`, entry]));
  const times = beat.clipIds.map((clipId) => items.get(clipId)?.reading_seconds).filter((value): value is number => value != null);
  return times.length ? Math.max(...times) : null;
}

const TEXT_BEAT_SECONDS = 4;
const HEADING_LIMIT = 120;
const PLATFORM_NAME: Record<string, string> = {
  tiktok: "TikTok",
  x: "X",
  instagram: "Instagram",
  youtube: "YouTube",
  threads: "Threads",
};

function textBeat(document: EditDocumentV2, role: "hook" | "outro", heading: string): Op<"add_text_clip"> {
  const canvas = document.canvas.duration_in_frames;
  const duration = Math.min(TEXT_BEAT_SECONDS * document.canvas.fps, canvas);
  return {
    kind: "add_text_clip",
    operation_id: id(),
    clip_id: `clip_${role}_${crypto.randomUUID().replaceAll("-", "")}`,
    track_id: "track_overlay",
    from_frame: role === "hook" ? 0 : canvas - duration,
    duration_in_frames: duration,
    heading: heading.slice(0, HEADING_LIMIT),
    body: "",
    style_slot: "title",
    source_role: role,
  };
}

/** Spec §8: the hook opens the video for 4 s with the run's title, over what is there. */
export const addHook = (document: EditDocumentV2, title: string) => textBeat(document, "hook", title);

/** Spec §8: the outro ends at the canvas end, 4 s, with the credit line. */
export const addOutro = (document: EditDocumentV2, credit: string) => textBeat(document, "outro", credit);

/** DESIGN §13.2's credit line, when the run names the original creator. */
export function creditLine(owner: string | null | undefined, platform: string | null | undefined): string {
  if (!owner) return "";
  return platform ? `Video: @${owner} · ${PLATFORM_NAME[platform] ?? platform}` : `Video: @${owner}`;
}

/** Seconds a text needs at the reading speed the importer uses. */
export const readingSeconds = (text: string) => text.length / READING_CPS;
