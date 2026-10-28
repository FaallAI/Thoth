/**
 * Story mode's edits as plain operation builders (spec 2026-10-27 §5.2, §9). Each returns the
 * revision-bound operations the editor commits as one undo step; none is applied here.
 */

import type { EditDocumentOperation, EditDocumentV2, EditorAsset, StudioImportItem } from "@/api/control-plane";

import { contentBox } from "@thoth/remotion-composition";

import { SAFE_ZONE } from "./SafeZone";
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

/**
 * The y a preset gives this clip. Top and Lower third keep the visible card clear of the
 * platform's header (top 10%) and buttons (bottom 18%), so a tall card sits higher or lower
 * than the preset's nominal offset; a card taller than the safe band keeps the preset's edge.
 * ponytail: motion's 8% zoom is not counted; count it if zoomed cards graze the buttons.
 */
export function presetY(document: EditDocumentV2, clip: Clip | undefined, preset: PositionPreset): number {
  const nominal = PRESET_Y[preset];
  if (preset === "middle" || !clip || !("asset_id" in clip)) return nominal;
  const ref = (document.asset_refs ?? []).find((entry) => entry.asset_id === clip.asset_id);
  const fit = "fit" in clip ? clip.fit : "cover";
  const half = (contentBox(fit, ref, document.canvas).height * positionOf(clip).scale) / 2;
  return preset === "lower"
    ? Math.min(nominal, 1 - SAFE_ZONE.bottom - half - 0.5)
    : Math.max(nominal, SAFE_ZONE.top + half - 0.5);
}

export function setPositionPreset(document: EditDocumentV2, clipIds: string[], preset: PositionPreset): Op<"set_clip_position">[] {
  return clipIds.map((clipId) => {
    const clip = clipOf(document, clipId);
    return {
      kind: "set_clip_position",
      operation_id: id(),
      clip_id: clipId,
      position: { ...positionOf(clip), y: presetY(document, clip, preset) },
    };
  });
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
  if (a.scene_id !== b.scene_id) {
    // Only clips that fill their own scenes trade them, and only with the neighbouring scene;
    // a card inside the main scene never moves the whole scene.
    const indexOf = (clip: Clip) => document.scenes.findIndex((scene) => scene.scene_id === clip.scene_id);
    const fills = (clip: Clip) => {
      const scene = document.scenes[indexOf(clip)];
      return Boolean(scene) && clip.from_frame === scene!.start_frame && clip.duration_in_frames === scene!.duration_in_frames;
    };
    if (!fills(a) || !fills(b) || indexOf(b) !== indexOf(a) + 1) return [];
    return [{ kind: "reorder_scene", operation_id: id(), scene_id: a.scene_id!, to_index: indexOf(b) }];
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
/** The importer's gap between cards (python domain/studio_layout.CARD_GAP). */
const CARD_GAP_SECONDS = 0.5;

/**
 * Every card of a beat lasts the chosen length, one after another from the first card's
 * start with the importer's gap, inside the first card's scene (or the canvas). When they
 * do not fit, each gets the share that does.
 */
export function setEachCardSeconds(document: EditDocumentV2, clipIds: string[], seconds: number): EditDocumentOperation[] {
  const clips = clipIds
    .map((clipId) => clipOf(document, clipId))
    .filter((clip): clip is Clip => Boolean(clip))
    .sort((a, b) => a.from_frame - b.from_frame);
  if (!clips.length) return [];
  const fps = document.canvas.fps;
  const gap = Math.round(CARD_GAP_SECONDS * fps);
  const start = clips[0]!.from_frame;
  const space = lastFrame(document, clips[0]!) - start - gap * (clips.length - 1);
  const each = Math.max(1, Math.min(Math.round(seconds * fps), Math.floor(space / clips.length)));
  return clips.flatMap((clip, index) => {
    const from = start + index * (each + gap);
    return [
      { kind: "move_clip", operation_id: id(), clip_id: clip.clip_id, target_track_id: clip.track_id, from_frame: from, ripple: false },
      { kind: "trim_clip_end", operation_id: id(), clip_id: clip.clip_id, end_frame: from + each },
    ] satisfies EditDocumentOperation[];
  });
}

/**
 * The first track of `kind` with nothing visible in [from, to), else a new one opened in the
 * same batch, so an added clip never overlaps another (an overlap blocks render and review).
 */
function trackFor(
  document: EditDocumentV2,
  kind: "overlay" | "b_roll",
  from: number,
  to: number,
): { trackId: string; operations: EditDocumentOperation[] } {
  const clips = document.clips ?? [];
  const free = document.tracks
    .filter((track) => track.kind === kind && !track.locked && !track.hidden)
    .sort((a, b) => a.order - b.order)
    .find((track) =>
      clips.every(
        (clip) => clip.track_id !== track.track_id || clip.hidden || clip.from_frame + clip.duration_in_frames <= from || clip.from_frame >= to,
      ),
    );
  if (free) return { trackId: free.track_id, operations: [] };
  const trackId = `track_story_${kind}_${crypto.randomUUID().replaceAll("-", "").slice(0, 12)}`;
  return {
    trackId,
    operations: [
      {
        kind: "add_track",
        operation_id: id(),
        track_id: trackId,
        track_kind: kind,
        label: kind === "overlay" ? "Story text" : "Story media",
        order: Math.max(...document.tracks.map((track) => track.order)) + 1,
      },
    ],
  };
}

/** The importer's placement for a contained card, CARD_WIDTH of the canvas wide. */
export function cardPosition(width: number | null | undefined, height: number | null | undefined, canvas: { width: number; height: number }) {
  const drawn = !width || !height ? canvas.width : Math.min(canvas.width, (canvas.height * width) / height);
  return { x: 0, y: CARD_CENTER_Y - 0.5, scale: (CARD_WIDTH * canvas.width) / drawn };
}

/**
 * A material joins its beat right after the beat's last clip, lasting as long as the
 * beat's longest clip. It is bound to no scene, and pulled back inside the canvas.
 */
export function addMaterialToBeat(document: EditDocumentV2, beat: Beat, asset: EditorAsset, role: StoryRole): EditDocumentOperation[] {
  const fps = document.canvas.fps;
  const lengths = beat.clipIds.map((clipId) => clipOf(document, clipId)?.duration_in_frames ?? 0);
  const longest = Math.min(Math.max(...lengths, 0) || 3 * fps, document.canvas.duration_in_frames);
  const duration = asset.kind === "video" && asset.duration_in_frames ? Math.min(longest, asset.duration_in_frames) : longest;
  const end = beat.startFrame + beat.durationInFrames;
  const from = Math.max(0, Math.min(end, document.canvas.duration_in_frames - duration));
  const { trackId, operations } = trackFor(document, "b_roll", from, from + duration);
  return [
    ...operations,
    {
      kind: "add_clip_from_asset",
      operation_id: id(),
      clip_id: `clip_${crypto.randomUUID().replaceAll("-", "")}`,
      track_id: trackId,
      asset_id: asset.asset_id,
      from_frame: from,
      duration_in_frames: duration,
      source_from_frame: 0,
      fit: "contain",
      position: cardPosition(asset.width, asset.height, document.canvas),
      source_role: role,
    },
  ];
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

function textBeat(document: EditDocumentV2, role: "hook" | "outro", heading: string): EditDocumentOperation[] {
  const canvas = document.canvas.duration_in_frames;
  const duration = Math.min(TEXT_BEAT_SECONDS * document.canvas.fps, canvas);
  const from = role === "hook" ? 0 : canvas - duration;
  // The importer's scene titles fill the overlay track, so the beat usually opens its own.
  const { trackId, operations } = trackFor(document, "overlay", from, from + duration);
  return [
    ...operations,
    {
      kind: "add_text_clip",
      operation_id: id(),
      clip_id: `clip_${role}_${crypto.randomUUID().replaceAll("-", "")}`,
      track_id: trackId,
      from_frame: from,
      duration_in_frames: duration,
      heading: heading.slice(0, HEADING_LIMIT),
      body: "",
      style_slot: "title",
      source_role: role,
    },
  ];
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
