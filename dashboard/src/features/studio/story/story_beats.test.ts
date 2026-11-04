/// <reference types="bun-types" />

import { expect, test } from "bun:test";

import { ROLE_BEAT, beatOfClip, beatOwnFrames, computeBeats, type Beat } from "./story_beats";

import { draft, item, storyDocument, storyInventory } from "./story-test-fixtures";

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

test("a material missing from a beat with no clips still shows that beat", () => {
  const missing = [...inventory, item("profile_page_000", "profile_page", "unresolved")];

  const evidence = computeBeats(story, missing).find((beat) => beat.id === "evidence");

  expect(evidence).toMatchObject({ clipIds: [], durationInFrames: 0 });
  expect(evidence?.missing.map((entry) => entry.item_id)).toEqual(["profile_page_000"]);
});

// The server's narration reads beats with domain/story_beats.py; one case file holds both to it.
import cases from "../story_beat_cases.json";

for (const entry of cases.cases) {
  test(`the shared beat case: ${entry.name}`, () => {
    const document = entry.document as unknown as Parameters<typeof computeBeats>[0];
    const items = Object.entries(entry.inventory_roles).map(
      ([item_id, role]) => ({ item_id, role, disposition: "attached", media_kind: "image" }) as never,
    );
    for (const [clipId, beat] of Object.entries(entry.expected_clip_beats)) {
      expect(beatOfClip(document, items, clipId)).toBe(beat as never);
    }
    expect(
      computeBeats(document, items).map((beat) => ({
        beat: beat.id,
        clip_ids: beat.clipIds,
        start_frame: beat.startFrame,
        duration_in_frames: beat.durationInFrames,
      })),
    ).toEqual(entry.expected_spans as never);
  });
}

const span = (id: Beat["id"], startFrame: number, durationInFrames: number): Beat => ({ id, startFrame, durationInFrames, clipIds: [], missing: [] });

test("a beat owns its frames until the next beat starts", () => {
  // The narrated stage1 draft: Main's video holds under Evidence and Reactions.
  const own = beatOwnFrames([span("main", 0, 735), span("evidence", 266, 258), span("reactions", 524, 242), span("footage", 766, 268)], 1034);

  expect([...own.entries()]).toEqual([["main", 266], ["evidence", 258], ["reactions", 242], ["footage", 268]]);
});

test("beat seconds always sum to the canvas, and a Hook over Main keeps its own time", () => {
  const own = beatOwnFrames(computeBeats(storyDocument(), storyInventory()), 300);

  expect([...own.values()].reduce((sum, frames) => sum + frames, 0)).toBe(300);
  expect(own.get("hook")).toBeGreaterThan(0);
});

test("beat ownership is counted by spans, not frame by frame", () => {
  // Final review, minor 7: a long canvas must not cost a loop per frame on every render.
  const started = performance.now();
  const own = beatOwnFrames([span("main", 0, 5_000_000), span("evidence", 2_000_000, 1_000_000)], 9_000_000);

  expect(performance.now() - started).toBeLessThan(50);
  // Main owns 0-2M and 3M-5M; Evidence owns 2M-3M and the uncovered tail 5M-9M (it started last).
  expect([...own.entries()]).toEqual([["main", 4_000_000], ["evidence", 5_000_000]]);
});
