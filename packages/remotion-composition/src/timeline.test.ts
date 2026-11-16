/// <reference types="bun-types" />

import { expect, test } from "bun:test";

import { clipLayers, visibleLanes, type EditDocumentV2, type TimelineClip } from "./timeline";

// Spec 2026-11-17, goal 5: clips that overlap on one lane stack as computed layers, as in an
// editor timeline; the lowest free layer, by start frame then document order.
const clip = (clip_id: string, from_frame: number, duration_in_frames: number, extra: object = {}) =>
  ({ clip_id, track_id: "track_overlay", kind: "text", from_frame, duration_in_frames, ...extra }) as unknown as TimelineClip;

const doc = (clips: TimelineClip[]) =>
  ({
    tracks: [{ track_id: "track_overlay", kind: "overlay", order: 2 }],
    clips,
  }) as unknown as EditDocumentV2;

test("clipLayers stacks overlaps and reuses a freed layer", () => {
  const title = clip("title", 0, 300);
  const card = clip("card", 100, 60);
  const credit = clip("credit", 200, 50); // the card ended at 160: layer 1 is free again
  const later = clip("later", 300, 30); // the title ended at 300: back on layer 0
  const layers = clipLayers([later, credit, card, title]);
  expect(Object.fromEntries(layers)).toEqual({ title: 0, card: 1, credit: 1, later: 0 });
});

test("a lane without overlaps keeps one layer and its order", () => {
  const [lane] = visibleLanes(doc([clip("b", 30, 30), clip("a", 0, 30)]));
  expect(lane.layers).toBe(1);
  expect(lane.clips.map((c) => c.clip_id)).toEqual(["a", "b"]);
  expect(lane.layered.map((c) => c.clip_id)).toEqual(["a", "b"]);
});

test("a lane draws its clips by layer, so a higher layer renders on top", () => {
  const [lane] = visibleLanes(doc([clip("card", 100, 60), clip("title", 0, 300), clip("credit", 120, 20)]));
  expect(lane.layers).toBe(3);
  expect(lane.layered.map((c) => c.clip_id)).toEqual(["title", "card", "credit"]);
  expect(lane.clips.map((c) => c.clip_id)).toEqual(["title", "card", "credit"]); // time order
  expect(lane.layerOf.get("credit")).toBe(2);
});

test("a hidden clip takes no layer", () => {
  const [lane] = visibleLanes(doc([clip("title", 0, 300), clip("ghost", 100, 60, { hidden: true }), clip("card", 120, 20)]));
  expect(lane.layerOf.has("ghost")).toBe(false);
  expect(lane.layerOf.get("card")).toBe(1);
  expect(lane.layers).toBe(2);
});
