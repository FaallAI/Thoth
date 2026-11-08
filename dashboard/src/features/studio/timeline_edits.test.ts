/// <reference types="bun-types" />

import { expect, test } from "bun:test";

import type { EditDocumentOperation, EditDocumentV2 } from "@/api/control-plane";
import { applyTimelineOperation } from "./timeline_domain";
import {
  closeGap,
  deleteClip,
  deleteClips,
  duplicateClips,
  moveClips,
  pasteClips,
  rippleDeleteClips,
  setClipsFlag,
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

// Operator, 2026-11-08: a clip that spans the whole removed stretch (a heading, a music bed)
// shortens by the removed length instead of blocking the edit; a clip cut part-way still blocks.
test("rippleDelete shortens a clip that spans the whole stretch, then pulls the rest left", () => {
  const doc = threeClips({ from: 0, length: 200 });
  const edit = rippleDelete(doc, "a");
  expect(shape(edit)).toEqual([
    { kind: "remove_clip", clip_id: "a" },
    { kind: "trim_clip_end", clip_id: "clip_music", end_frame: 140 },
    { kind: "move_clip", clip_id: "b", target_track_id: "track_main", from_frame: 0, ripple: false },
    { kind: "move_clip", clip_id: "c", target_track_id: "track_main", from_frame: 70, ripple: false },
  ]);
  const after = applies(doc, edit);
  expect(after.clips!.find((clip) => clip.clip_id === "clip_music")!.duration_in_frames).toBe(140);
});

test("rippleDelete still refuses a spanning clip that is locked", () => {
  expect(rippleDelete(threeClips({ from: 0, length: 200, locked: true }), "a").refusal).toBe("later_locked");
});

test("rippleDelete refuses a clip that lies exactly on the stretch", () => {
  expect(rippleDelete(threeClips({ from: 0, length: 60 }), "a").refusal).toBe("crossing");
});

test("closeGap shortens a clip that spans the whole gap", () => {
  const doc = threeClips({ from: 90, length: 70 });
  const edit = closeGap(doc, "track_main", 110);
  expect(shape(edit)).toEqual([
    { kind: "trim_clip_end", clip_id: "clip_music", end_frame: 130 },
    { kind: "move_clip", clip_id: "c", target_track_id: "track_main", from_frame: 100, ripple: false },
  ]);
  applies(doc, edit);
});

// Final pass 2026-11-08: the server keeps a scene-bound clip inside its scene; the client must not
// make an edit the server then refuses.
test("rippleDelete refuses when a later clip would leave its scene", () => {
  const doc = threeClips();
  doc.scenes.push({ scene_id: "scene_late", role: "source", start_frame: 100, duration_in_frames: 200, clip_ids: ["clip_music"] });
  doc.clips!.find((clip) => clip.clip_id === "clip_music")!.scene_id = "scene_late";
  expect(rippleDelete(doc, "a").refusal).toBe("scene");
});

// Tier 2 (spec 2026-11-08 §6): one edit for the whole selection, or none.
test("deleteClips removes every clip in one batch and refuses when one is locked", () => {
  const doc = timelineDocument();
  expect(shape(deleteClips(doc, ["clip_main", "clip_music"]))).toEqual([
    { kind: "remove_clip", clip_id: "clip_main" },
    { kind: "remove_clip", clip_id: "clip_music" },
  ]);
  expect(deleteClips(doc, ["clip_main", "clip_locked"])).toEqual({ operations: [], refusal: "locked" });
});

test("rippleDeleteClips closes every removed stretch on the evolving document", () => {
  const doc = threeClips();
  const edit = rippleDeleteClips(doc, ["a", "clip_music"]);
  expect(edit.refusal).toBeUndefined();
  const after = applies(doc, edit);
  expect(after.clips!.map((clip) => [clip.clip_id, clip.from_frame])).toEqual([
    ["b", 0],
    ["c", 40],
  ]);
});

test("rippleDeleteClips refuses all when one stretch is refused", () => {
  expect(rippleDeleteClips(threeClips({ from: 30, length: 60 }), ["a", "c"]).refusal).toBe("crossing");
});

test("moveClips moves every clip by the same frames on its own track", () => {
  const doc = timelineDocument();
  expect(shape(moveClips(doc, ["clip_main", "clip_music"], 30))).toEqual([
    { kind: "move_clip", clip_id: "clip_main", target_track_id: "track_main", from_frame: 30, ripple: false },
    { kind: "move_clip", clip_id: "clip_music", target_track_id: "track_music", from_frame: 180, ripple: false },
  ]);
  expect(moveClips(doc, ["clip_main", "clip_locked"], 30).refusal).toBe("locked");
  expect(moveClips(doc, ["clip_main", "clip_music"], -10).refusal).toBe("outside");
  expect(moveClips(doc, ["clip_main", "clip_music"], 100).refusal).toBe("outside");
});

test("setClipsFlag hides every clip, and refuses hiding when one is locked", () => {
  const doc = timelineDocument();
  expect(shape(setClipsFlag(doc, ["clip_main", "clip_music"], "hidden", true))).toEqual([
    { kind: "set_clip_hidden", clip_id: "clip_main", hidden: true },
    { kind: "set_clip_hidden", clip_id: "clip_music", hidden: true },
  ]);
  expect(setClipsFlag(doc, ["clip_main", "clip_locked"], "hidden", true).refusal).toBe("locked");
  expect(setClipsFlag(doc, ["clip_main", "clip_locked"], "locked", true).operations).toHaveLength(2);
});

// Tier 2 (spec 2026-11-08 §6): copies inside the open draft, never through the system clipboard.
const withoutNewId = (operation: Record<string, unknown>) => {
  const { new_clip_id: _id, ...rest } = operation;
  return rest;
};
test("pasteClips places copies at a frame on their own tracks, keeping their offsets", () => {
  const doc = threeClips({ from: 100, length: 30 });
  expect(shape(pasteClips(doc, ["c", "clip_music"], 200)).map(withoutNewId)).toEqual([
    { kind: "duplicate_clip", clip_id: "clip_music", track_id: "track_music", from_frame: 200 },
    { kind: "duplicate_clip", clip_id: "c", track_id: "track_main", from_frame: 230 },
  ]);
  applies(doc, pasteClips(doc, ["c", "clip_music"], 200));
});

test("pasteClips refuses a filled Main video track, a deleted clip and the canvas end", () => {
  const doc = threeClips();
  expect(pasteClips(doc, ["a"], 30).refusal).toBe("no_room");
  expect(pasteClips(doc, ["gone"], 0).refusal).toBe("gone");
  expect(pasteClips(doc, ["c"], 280).refusal).toBe("outside");
});

test("duplicateClips places the copy right after the selection's end", () => {
  const doc = threeClips();
  expect(shape(duplicateClips(doc, ["c"])).map(withoutNewId)).toEqual([
    { kind: "duplicate_clip", clip_id: "c", track_id: "track_main", from_frame: 160 },
  ]);
});
