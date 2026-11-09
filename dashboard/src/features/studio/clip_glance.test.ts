/// <reference types="bun-types" />

import { expect, test } from "bun:test";

import { glanceWindow, peakSlice, stripTiles } from "./clip_glance";

// Tier 3b: a clip shows the stretch of its source that it plays, at its speed.
test("glanceWindow is the stretch of source a clip plays", () => {
  expect(glanceWindow({ source_from_frame: 30, duration_in_frames: 60 }, 30)).toEqual({ fromSeconds: 1, seconds: 2 });
  expect(glanceWindow({ source_from_frame: 30, duration_in_frames: 60, speed: 2 }, 30)).toEqual({ fromSeconds: 1, seconds: 4 });
});

const strip = { image: "data:image/jpeg;base64,AAAA", frame_width: 128, frame_height: 72, frames: 10, seconds_per_frame: 1 };

test("stripTiles keeps each frame's shape and shows the source frame under each tile", () => {
  // A 64 px tile at 36 px tall; the clip plays seconds 1 to 3 across 256 px, so 4 tiles.
  const tiles = stripTiles(strip, { fromSeconds: 1, seconds: 2 }, 256, 36);
  expect(tiles.map((tile) => [tile.left, tile.width, tile.frame])).toEqual([
    [0, 64, 1],
    [64, 64, 1],
    [128, 64, 2],
    [192, 64, 2],
  ]);
});

test("stripTiles never points past the strip's last frame", () => {
  const tiles = stripTiles(strip, { fromSeconds: 9, seconds: 4 }, 128, 36);
  expect(tiles.every((tile) => tile.frame <= 9)).toBe(true);
});

const peaks = { seconds_per_peak: 0.5, values: [1, 2, 3, 4, 5, 6] };

test("peakSlice is the peaks inside a slipped clip's window", () => {
  expect(peakSlice(peaks, { fromSeconds: 1, seconds: 1 })).toEqual([3, 4]);
});

test("peakSlice stops at the end of the peaks", () => {
  expect(peakSlice(peaks, { fromSeconds: 2, seconds: 5 })).toEqual([5, 6]);
});

test("a very wide clip widens its tiles instead of stopping short", () => {
  // Portrait frames make 20 px tiles at 36 px tall; 8000 px would need 400, more than the cap.
  const portrait = { ...strip, frame_width: 40 };
  const tiles = stripTiles(portrait, { fromSeconds: 0, seconds: 10 }, 8000, 36);
  expect(tiles.length).toBeLessThanOrEqual(200);
  const last = tiles.at(-1)!;
  expect(last.left + last.width).toBe(8000);
  expect(tiles[0]!.size).toBe(40);
});
