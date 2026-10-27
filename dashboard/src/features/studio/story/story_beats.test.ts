/// <reference types="bun-types" />

import { expect, test } from "bun:test";

import type { EditDocumentV2, StudioImportItem } from "@/api/control-plane";

import { ROLE_BEAT, beatOfClip, computeBeats } from "./story_beats";

type Clip = NonNullable<EditDocumentV2["clips"]>[number];

const track = (track_id: string, kind: string, order: number, clip_ids: string[]) =>
  ({ track_id, kind, label: track_id, order, hidden: false, muted: false, locked: false, clip_ids }) as EditDocumentV2["tracks"][number];

const text = (clip_id: string, from: number, length: number, extra: Partial<Clip> = {}) =>
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

const video = (clip_id: string, track_id: string, from: number, length: number, extra: Partial<Clip> = {}) =>
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

function draft(clips: Clip[]): EditDocumentV2 {
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
    asset_refs: [],
  } as EditDocumentV2;
}

const item = (item_id: string, role: StudioImportItem["role"], disposition: StudioImportItem["disposition"]) =>
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

const story = draft([
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
const inventory = [
  item("main_000", "main", "attached"),
  item("comment_card_000", "comment_card", "attached"),
  item("comment_card_001", "comment_card", "attached"),
  item("comment_card_002", "comment_card", "unresolved"),
  item("footage_000", "footage", "attached"),
  { ...item("comment_000", "comment", "unresolved"), media_kind: "none" as const },
];

test("every story role maps to its beat", () => {
  expect(ROLE_BEAT).toEqual({
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
  });
});

test("beats are ordered by their first clip and span their clips", () => {
  const beats = computeBeats(story, inventory);

  expect(beats.map((beat) => [beat.id, beat.startFrame, beat.durationInFrames])).toEqual([
    ["hook", 0, 120],
    ["main", 0, 150],
    ["reactions", 60, 80],
    ["footage", 150, 150],
  ]);
  expect(beats.find((beat) => beat.id === "reactions")?.clipIds).toEqual([
    "clip_comment_card_000",
    "clip_comment_card_001",
  ]);
});

test("a scene's own text takes its scene's beat, never hook or outro", () => {
  expect(beatOfClip(story, inventory, "clip_title")).toBe("main");
  expect(beatOfClip(story, inventory, "clip_source")).toBe("footage");
  expect(beatOfClip(story, inventory, "clip_hook")).toBe("hook");
});

test("a clip with no role, no item and no scene belongs to no beat", () => {
  expect(beatOfClip(story, inventory, "clip_x")).toBeNull();
  expect(computeBeats(story, inventory).flatMap((beat) => beat.clipIds)).not.toContain("clip_x");
});

test("hidden clips leave their beat", () => {
  expect(computeBeats(story, inventory).flatMap((beat) => beat.clipIds)).not.toContain("clip_comment_card_009");
});

test("an unresolved material is missing from its beat; a quote never is", () => {
  const reactions = computeBeats(story, inventory).find((beat) => beat.id === "reactions");
  expect(reactions?.missing.map((entry) => entry.item_id)).toEqual(["comment_card_002"]);
});

test("a draft with no clips has no beats", () => {
  expect(computeBeats(draft([]), [])).toEqual([]);
});
