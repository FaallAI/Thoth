/// <reference types="bun-types" />

import { expect, test } from "bun:test";

import type { EditorAsset } from "@/api/control-plane";

import { computeBeats } from "./story_beats";
import {
  addHook,
  addMaterialToBeat,
  addOutro,
  creditLine,
  cardPosition,
  longestReading,
  removeFromBeat,
  setClipSeconds,
  setEachCardSeconds,
  setEmphasis,
  setMotion,
  setPositionPreset,
  swapClips,
} from "./story_edits";
import { storyDocument, storyInventory } from "./story-test-fixtures";

const cards = ["clip_comment_card_000", "clip_comment_card_001"];
const reactions = () => computeBeats(storyDocument(), storyInventory()).find((beat) => beat.id === "reactions")!;

test("a position preset moves y only and keeps x and scale", () => {
  const document = storyDocument();
  const card = document.clips!.find((clip) => clip.clip_id === "clip_comment_card_000") as { position?: unknown };
  card.position = { x: 0.1, y: -0.24, scale: 0.76 };

  const [lower, plain] = setPositionPreset(document, cards, "lower");

  expect(lower).toMatchObject({ kind: "set_clip_position", clip_id: "clip_comment_card_000", position: { x: 0.1, y: 0.22, scale: 0.76 } });
  expect(plain).toMatchObject({ clip_id: "clip_comment_card_001", position: { x: 0, y: 0.22, scale: 1 } });
  expect(setPositionPreset(document, cards, "top")[0]).toMatchObject({ position: { y: -0.24 } });
  expect(setPositionPreset(document, cards, "middle")[0]).toMatchObject({ position: { y: 0 } });
});

test("swapping two cards keeps the pair's span", () => {
  const operations = swapClips(storyDocument(), "clip_comment_card_000", "clip_comment_card_001");

  expect(operations).toEqual([
    expect.objectContaining({ kind: "move_clip", clip_id: "clip_comment_card_001", target_track_id: "track_b_roll", from_frame: 60 }),
    expect.objectContaining({ kind: "move_clip", clip_id: "clip_comment_card_000", target_track_id: "track_b_roll", from_frame: 100 }),
  ]);
});

test("swapping clips of two scenes reorders the scenes", () => {
  expect(swapClips(storyDocument(), "clip_main_000", "clip_footage_000")).toEqual([
    expect.objectContaining({ kind: "reorder_scene", scene_id: "scene_001", to_index: 1 }),
  ]);
});

test("a single clip's length is trimmed, never past its scene", () => {
  expect(setClipSeconds(storyDocument(), ["clip_comment_card_001"], 3)).toEqual([
    expect.objectContaining({ kind: "trim_clip_end", clip_id: "clip_comment_card_001", end_frame: 150 }),
  ]);
});

test("motion, emphasis and removal apply to each clip", () => {
  expect(setMotion(cards, "slow_zoom").map((operation) => [operation.kind, operation.clip_id])).toEqual([
    ["set_clip_motion", "clip_comment_card_000"],
    ["set_clip_motion", "clip_comment_card_001"],
  ]);
  expect(setEmphasis(cards, true, false)[1]).toMatchObject({ kind: "set_clip_emphasis", highlight: true, arrow: false });
  expect(removeFromBeat("clip_comment_card_000")).toMatchObject({ kind: "set_clip_hidden", hidden: true });
});

test("a material joins the beat after its last clip, placed as the importer places cards", () => {
  const asset = { asset_id: "asset_new", kind: "image", width: 1080, height: 1350 } as EditorAsset;

  const operation = addMaterialToBeat(storyDocument(), reactions(), asset, "comment_card").at(-1)!;

  expect(operation).toMatchObject({
    kind: "add_clip_from_asset",
    asset_id: "asset_new",
    from_frame: 140,
    duration_in_frames: 40,
    fit: "contain",
    position: { x: 0, y: -0.24, scale: 0.76 },
    source_role: "comment_card",
  });
  expect((operation as { clip_id: string }).clip_id).toMatch(/^clip_/);
});

test("a card added at the canvas end is pulled back inside it", () => {
  const asset = { asset_id: "asset_new", kind: "image", width: 1080, height: 1350 } as EditorAsset;
  const late = { ...reactions(), startFrame: 250, durationInFrames: 50 };

  expect(addMaterialToBeat(storyDocument(), late, asset, "comment_card").at(-1)).toMatchObject({ from_frame: 260, duration_in_frames: 40 });
});

test("a wide card is drawn the importer's width of the canvas", () => {
  expect(cardPosition(1080, 400, { width: 1080, height: 1920 })).toEqual({ x: 0, y: -0.24, scale: 0.76 });
  expect(cardPosition(1080, 2400, { width: 1080, height: 1920 }).scale).toBeCloseTo(0.76 * (1080 / (1920 * 1080 / 2400)), 10);
});

test("the longest card's reading time comes from the import", () => {
  const inventory = storyInventory().map((entry) =>
    entry.item_id === "comment_card_001" ? { ...entry, reading_seconds: 3.2 } : entry,
  );
  expect(longestReading(reactions(), inventory)).toBe(3.2);
});

test("a hook opens the video for four seconds with the run's title", () => {
  expect(addHook(storyDocument(), "Kabut asap Kalteng").at(-1)).toMatchObject({
    kind: "add_text_clip",
    from_frame: 0,
    duration_in_frames: 120,
    heading: "Kabut asap Kalteng",
    body: "",
    style_slot: "title",
    source_role: "hook",
  });
  expect((addHook(storyDocument(), "x".repeat(200)).at(-1) as { heading: string }).heading).toHaveLength(120);
});

test("an outro closes the video for four seconds with the credit line", () => {
  expect(addOutro(storyDocument(), "Video: @cat · TikTok").at(-1)).toMatchObject({
    kind: "add_text_clip",
    from_frame: 180,
    duration_in_frames: 120,
    heading: "Video: @cat · TikTok",
    source_role: "outro",
  });
});

test("a canvas shorter than four seconds holds the whole beat", () => {
  const short = storyDocument();
  short.canvas.duration_in_frames = 90;
  expect(addHook(short, "t").at(-1)).toMatchObject({ from_frame: 0, duration_in_frames: 90 });
  expect(addOutro(short, "c").at(-1)).toMatchObject({ from_frame: 0, duration_in_frames: 90 });
});

test("the credit line names the original creator and platform, when known", () => {
  expect(creditLine("cat", "tiktok")).toBe("Video: @cat · TikTok");
  expect(creditLine("bmkg", "youtube")).toBe("Video: @bmkg · YouTube");
  expect(creditLine("cat", undefined)).toBe("Video: @cat");
  expect(creditLine(undefined, "x")).toBe("");
});

// Final review C1/I4: Story additions and lengths never stack clips on a taken track.
import type { EditDocumentOperation, EditDocumentV2 } from "@/api/control-plane";
import { applyTimelineOperation, timelineIssues } from "../timeline_domain";

const applied = (document: EditDocumentV2, operations: EditDocumentOperation[], assets: Record<string, EditorAsset> = {}) =>
  operations.reduce((next, operation) => applyTimelineOperation(next, operation, assets), document);

test("a hook and an outro over the scene titles go on a free text track", () => {
  const document = storyDocument();
  document.clips = document.clips!.filter((clip) => clip.clip_id !== "clip_hook");
  document.tracks.find((track) => track.track_id === "track_text")!.clip_ids = [];
  document.tracks = document.tracks.filter((track) => track.track_id !== "track_text");
  expect(timelineIssues(document)).toEqual([]);

  const withHook = applied(document, addHook(document, "Kabut asap"));
  const withBoth = applied(withHook, addOutro(withHook, "Video: @cat · TikTok"));

  expect(timelineIssues(withBoth)).toEqual([]);
  const tracks = withBoth.tracks.filter((track) => track.kind === "overlay");
  expect(tracks).toHaveLength(2);
  // The second text beat reuses the track the first one opened.
  expect(tracks[1]!.clip_ids).toHaveLength(2);
});

test("a material added after the beat goes on a free b-roll track", () => {
  const document = storyDocument();
  const asset = { asset_id: "asset_new", kind: "image", width: 1080, height: 1350, project_id: "project_001", validation_state: "ready" } as EditorAsset;

  const result = applied(document, addMaterialToBeat(document, reactions(), asset, "comment_card"), { asset_new: asset });

  expect(timelineIssues(result)).toEqual([]);
});

test("each card lasts the chosen length, one after another inside the scene", () => {
  expect(setEachCardSeconds(storyDocument(), cards, 1)).toEqual([
    expect.objectContaining({ kind: "move_clip", clip_id: "clip_comment_card_000", from_frame: 60 }),
    expect.objectContaining({ kind: "trim_clip_end", clip_id: "clip_comment_card_000", end_frame: 90 }),
    expect.objectContaining({ kind: "move_clip", clip_id: "clip_comment_card_001", from_frame: 105 }),
    expect.objectContaining({ kind: "trim_clip_end", clip_id: "clip_comment_card_001", end_frame: 135 }),
  ]);
  const long = applied(storyDocument(), setEachCardSeconds(storyDocument(), cards, 3));
  expect(timelineIssues(long)).toEqual([]);
  const scene = long.scenes[0]!;
  for (const id of cards) {
    const clip = long.clips!.find((entry) => entry.clip_id === id)!;
    expect(clip.from_frame + clip.duration_in_frames).toBeLessThanOrEqual(scene.start_frame + scene.duration_in_frames);
  }
});

test("a card and a clip of another scene do not trade scenes", () => {
  const document = storyDocument();
  // The reaction card sits inside the main scene without filling it.
  expect(swapClips(document, "clip_comment_card_001", "clip_footage_000")).toEqual([]);
});
