/// <reference types="bun-types" />

import { expect, test } from "bun:test";

import type { EditDocumentOperation, EditDocumentV2 } from "@/api/control-plane";
import { applyTimelineOperation } from "./timeline_domain";
import {
  closeGap,
  deleteClip,
  gapAt,
  moveToTrack,
  moveTrack,
  removeTrack,
  rippleDelete,
  setClipFlag,
  splitAt,
  type Edit,
} from "./timeline_edits";
import { timelineDocument } from "./timeline-test-fixtures";

type Clip = NonNullable<EditDocumentV2["clips"]>[number];

/** Three main clips (0–60, 60–100, 130–160) and one music clip; B-roll emptied of its locked clip. */
function threeClips(music: { from: number; length: number; locked?: boolean } = { from: 100, length: 30 }): EditDocumentV2 {
  const doc = timelineDocument();
  const main = doc.clips!.find((clip) => clip.clip_id === "clip_main")!;
  const at = (clip_id: string, from_frame: number, duration_in_frames: number): Clip => ({ ...main, clip_id, from_frame, duration_in_frames });
  const music_ = { ...doc.clips!.find((clip) => clip.clip_id === "clip_music")!, from_frame: music.from, duration_in_frames: music.length, locked: music.locked ?? false };
  doc.clips = [at("a", 0, 60), at("b", 60, 40), at("c", 130, 30), music_];
  for (const track of doc.tracks) {
    if (track.track_id === "track_main") track.clip_ids = ["a", "b", "c"];
    if (track.track_id === "track_broll") track.clip_ids = [];
  }
  doc.scenes[0]!.clip_ids = ["a"];
  return doc;
}

const shape = (edit: Edit) =>
  edit.operations.map((operation) => {
    const { operation_id: _id, ...rest } = operation as EditDocumentOperation & { operation_id: string };
    return rest;
  });

/** The client applies the batch the way `commit_operations` does. */
const applies = (doc: EditDocumentV2, edit: Edit) =>
  edit.operations.reduce((current, operation) => applyTimelineOperation(current, operation, {}), doc);

test("deleteClip removes an unlocked clip and refuses a locked one", () => {
  const doc = timelineDocument();
  expect(shape(deleteClip(doc, "clip_main"))).toEqual([{ kind: "remove_clip", clip_id: "clip_main" }]);
  expect(deleteClip(doc, "clip_locked")).toEqual({ operations: [], refusal: "locked" });
});

test("rippleDelete pulls the later clips of every track left", () => {
  const doc = threeClips();
  const edit = rippleDelete(doc, "a");
  expect(shape(edit)).toEqual([
    { kind: "remove_clip", clip_id: "a" },
    { kind: "move_clip", clip_id: "b", target_track_id: "track_main", from_frame: 0, ripple: false },
    { kind: "move_clip", clip_id: "c", target_track_id: "track_main", from_frame: 70, ripple: false },
    { kind: "move_clip", clip_id: "clip_music", target_track_id: "track_music", from_frame: 40, ripple: false },
  ]);
  const after = applies(doc, edit);
  expect(after.clips!.map((clip) => [clip.clip_id, clip.from_frame])).toEqual([
    ["b", 0],
    ["c", 70],
    ["clip_music", 40],
  ]);
});

test("rippleDelete refuses when another track has a clip in the removed stretch", () => {
  expect(rippleDelete(threeClips({ from: 30, length: 60 }), "a")).toEqual({ operations: [], refusal: "crossing" });
});

test("rippleDelete refuses when a clip that would move is locked", () => {
  expect(rippleDelete(threeClips({ from: 100, length: 30, locked: true }), "a")).toEqual({ operations: [], refusal: "later_locked" });
});

test("splitAt cuts inside the clip only", () => {
  const doc = timelineDocument();
  const edit = splitAt(doc, "clip_main", 60);
  expect(edit.operations).toHaveLength(1);
  const split = edit.operations[0] as Extract<EditDocumentOperation, { kind: "split_clip" }>;
  expect(split).toMatchObject({ kind: "split_clip", clip_id: "clip_main", split_frame: 60 });
  expect(split.left_clip_id).not.toBe(split.right_clip_id);
  expect(splitAt(doc, "clip_main", 0).refusal).toBe("outside");
  expect(splitAt(doc, "clip_main", 120).refusal).toBe("outside");
  applies(doc, edit);
});

test("moveToTrack moves to a compatible track and refuses an incompatible one", () => {
  const doc = timelineDocument();
  expect(shape(moveToTrack(doc, "clip_main", "track_broll"))).toEqual([
    { kind: "move_clip", clip_id: "clip_main", target_track_id: "track_broll", from_frame: 0, ripple: false },
  ]);
  expect(moveToTrack(doc, "clip_main", "track_music").refusal).toBe("incompatible");
});

test("gapAt finds a stretch between two clips only", () => {
  const doc = threeClips();
  expect(gapAt(doc, "track_main", 110)).toEqual({ start: 100, end: 130 });
  expect(gapAt(doc, "track_main", 200)).toBeNull();
  expect(gapAt(doc, "track_main", 30)).toBeNull();
});

test("closeGap pulls the later clips of every track left", () => {
  const doc = threeClips({ from: 130, length: 30 });
  const edit = closeGap(doc, "track_main", 110);
  expect(shape(edit)).toEqual([
    { kind: "move_clip", clip_id: "c", target_track_id: "track_main", from_frame: 100, ripple: false },
    { kind: "move_clip", clip_id: "clip_music", target_track_id: "track_music", from_frame: 100, ripple: false },
  ]);
  applies(doc, edit);
  expect(closeGap(threeClips({ from: 105, length: 20 }), "track_main", 110).refusal).toBe("crossing");
  expect(closeGap(doc, "track_main", 30).refusal).toBe("no_gap");
});

test("moveTrack swaps order with its neighbour and refuses at the edge", () => {
  const doc = timelineDocument();
  const edit = moveTrack(doc, "track_broll", -1);
  expect(shape(edit)).toEqual([
    { kind: "reorder_track", track_id: "track_broll", order: 0 },
    { kind: "reorder_track", track_id: "track_main", order: 1 },
  ]);
  applies(doc, edit);
  expect(moveTrack(doc, "track_main", -1).refusal).toBe("edge");
});

test("removeTrack removes an empty unlocked track only", () => {
  const doc = timelineDocument();
  expect(removeTrack(doc, "track_captions").refusal).toBe("locked");
  expect(removeTrack(doc, "track_main").refusal).toBe("not_empty");
  const emptied = threeClips();
  expect(shape(removeTrack(emptied, "track_broll"))).toEqual([{ kind: "remove_empty_track", track_id: "track_broll" }]);
  applies(emptied, removeTrack(emptied, "track_broll"));
});

test("setClipFlag hides and locks, and a locked clip can still be unlocked", () => {
  const doc = timelineDocument();
  expect(shape(setClipFlag(doc, "clip_main", "hidden", true))).toEqual([{ kind: "set_clip_hidden", clip_id: "clip_main", hidden: true }]);
  expect(setClipFlag(doc, "clip_locked", "hidden", true).refusal).toBe("locked");
  expect(shape(setClipFlag(doc, "clip_locked", "locked", false))).toEqual([{ kind: "set_clip_locked", clip_id: "clip_locked", locked: false }]);
});
