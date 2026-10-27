/// <reference types="bun-types" />

import { expect, test } from "bun:test";

import type { EditorAsset } from "@/api/control-plane";

import { computeBeats } from "./story_beats";
import {
  addMaterialToBeat,
  cardPosition,
  longestReading,
  removeFromBeat,
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

test("each card's length is trimmed, never past its scene", () => {
  expect(setEachCardSeconds(storyDocument(), cards, 3)).toEqual([
    expect.objectContaining({ kind: "trim_clip_end", clip_id: "clip_comment_card_000", end_frame: 150 }),
    expect.objectContaining({ kind: "trim_clip_end", clip_id: "clip_comment_card_001", end_frame: 150 }),
  ]);
  expect(setEachCardSeconds(storyDocument(), cards, 1)[0]).toMatchObject({ end_frame: 90 });
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

  const operation = addMaterialToBeat(storyDocument(), reactions(), asset, "comment_card");

  expect(operation).toMatchObject({
    kind: "add_clip_from_asset",
    track_id: "track_b_roll",
    asset_id: "asset_new",
    from_frame: 140,
    duration_in_frames: 40,
    fit: "contain",
    position: { x: 0, y: -0.24, scale: 0.76 },
    source_role: "comment_card",
  });
  expect(operation.clip_id).toMatch(/^clip_/);
});

test("a card added at the canvas end is pulled back inside it", () => {
  const asset = { asset_id: "asset_new", kind: "image", width: 1080, height: 1350 } as EditorAsset;
  const late = { ...reactions(), startFrame: 250, durationInFrames: 50 };

  expect(addMaterialToBeat(storyDocument(), late, asset, "comment_card")).toMatchObject({ from_frame: 260, duration_in_frames: 40 });
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
