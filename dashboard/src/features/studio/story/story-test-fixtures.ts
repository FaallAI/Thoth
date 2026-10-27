/**
 * A Story-mode draft and its import inventory, shared by the Story tests.
 *
 * Main over scene 1 with two reaction cards (one found only through its inventory item),
 * footage over scene 2, a hook, a hidden card and an orphan clip.
 */

import type { EditDocumentV2, StudioImportItem } from "@/api/control-plane";

type Clip = NonNullable<EditDocumentV2["clips"]>[number];

const track = (track_id: string, kind: string, order: number, clip_ids: string[]) =>
  ({ track_id, kind, label: track_id, order, hidden: false, muted: false, locked: false, clip_ids }) as EditDocumentV2["tracks"][number];

export const text = (clip_id: string, from: number, length: number, extra: Partial<Clip> = {}) =>
  ({
    kind: "text",
    clip_id,
    track_id: "track_overlay",
    scene_id: null,
    from_frame: from,
    duration_in_frames: length,
    ownership: "ai_managed",
    hidden: false,
    locked: false,
    heading: clip_id,
    body: "",
    style_slot: "title",
    ...extra,
  }) as Clip;

export const video = (clip_id: string, track_id: string, from: number, length: number, extra: Partial<Clip> = {}) =>
  ({
    kind: "video",
    clip_id,
    track_id,
    scene_id: null,
    from_frame: from,
    duration_in_frames: length,
    ownership: "ai_managed",
    hidden: false,
    locked: false,
    asset_id: `asset_${clip_id}`,
    source_from_frame: 0,
    fit: "cover",
    blur_enabled: false,
    motion: "none",
    emphasis: { highlight: false, arrow: false },
    ...extra,
  }) as Clip;

export function draft(clips: Clip[]): EditDocumentV2 {
  const on = (trackId: string) => clips.filter((clip) => clip.track_id === trackId).map((clip) => clip.clip_id);
  return {
    schema_version: 2,
    document_id: "edoc_story",
    project_id: "project_001",
    revision: 3,
    template: { template_id: "vertical_text_story", version: 1 },
    canvas: { width: 1080, height: 1920, fps: 30, duration_in_frames: 300 },
    scenes: [
      { scene_id: "scene_001", role: "title", start_frame: 0, duration_in_frames: 150, clip_ids: ["clip_title"] },
      { scene_id: "scene_002", role: "source", start_frame: 150, duration_in_frames: 150, clip_ids: ["clip_source"] },
    ],
    tracks: [
      track("track_main_video", "main_video", 0, on("track_main_video")),
      track("track_b_roll", "b_roll", 1, on("track_b_roll")),
      track("track_overlay", "overlay", 2, on("track_overlay")),
    ],
    clips,
    // Cards are stills; every other media clip is a video long enough for its clip.
    asset_refs: clips
      .filter((clip) => clip.kind === "video")
      .map((clip) => ({
        asset_id: (clip as { asset_id: string }).asset_id,
        project_id: "project_001",
        kind: clip.clip_id.includes("card") ? ("image" as const) : ("video" as const),
        duration_in_frames: clip.clip_id.includes("card") ? null : 900,
        width: 1080,
        height: clip.clip_id.includes("card") ? 1350 : 1920,
        fps: null,
        has_audio: false,
        validation_state: "ready" as const,
        checksum: null,
      })),
  } as EditDocumentV2;
}

export const item = (item_id: string, role: StudioImportItem["role"], disposition: StudioImportItem["disposition"]) =>
  ({
    item_id,
    role,
    order: 0,
    label: item_id,
    platform: null,
    media_kind: "image",
    scene_id: null,
    reason: null,
    disposition,
  }) as StudioImportItem;

export const storyDocument = (): EditDocumentV2 => draft([
  text("clip_title", 0, 150, { scene_id: "scene_001" }),
  video("clip_main_000", "track_main_video", 0, 150, { scene_id: "scene_001" }),
  text("clip_source", 150, 150, { scene_id: "scene_002" }),
  video("clip_footage_000", "track_b_roll", 150, 150, { scene_id: "scene_002", source_role: "footage" }),
  video("clip_comment_card_000", "track_b_roll", 60, 40, { scene_id: "scene_001", source_role: "comment_card" }),
  // No source_role: a draft made before Story mode, found through its inventory item.
  video("clip_comment_card_001", "track_b_roll", 100, 40, { scene_id: "scene_001" }),
  video("clip_comment_card_009", "track_b_roll", 20, 20, { source_role: "comment_card", hidden: true }),
  text("clip_hook", 0, 120, { source_role: "hook" }),
  video("clip_x", "track_b_roll", 10, 10),
]);
export const storyInventory = (): StudioImportItem[] => [
  item("main_000", "main", "attached"),
  item("comment_card_000", "comment_card", "attached"),
  item("comment_card_001", "comment_card", "attached"),
  item("comment_card_002", "comment_card", "unresolved"),
  item("footage_000", "footage", "attached"),
  { ...item("comment_000", "comment", "unresolved"), media_kind: "none" as const },
];
