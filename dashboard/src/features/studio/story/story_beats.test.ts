/// <reference types="bun-types" />

import { expect, test } from "bun:test";

import { ROLE_BEAT, beatOfClip, computeBeats } from "./story_beats";

import { draft, storyDocument, storyInventory } from "./story-test-fixtures";

const story = storyDocument();
const inventory = storyInventory();

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
