/// <reference types="bun-types" />

import { expect, test } from "bun:test";

import { blurBoxes } from "@thoth/remotion-composition/blur";

const CANVAS = { width: 1080, height: 1920 };
const BAND = { x: 0.1, y: 0.65, w: 0.8, h: 0.0878, from_frame: null, to_frame: null };

type Clip = Parameters<typeof blurBoxes>[0];

function clip(overrides: Partial<Clip> = {}): Clip {
  return {
    fit: "cover",
    crop: null,
    position: null,
    source_from_frame: 0,
    blur_regions: [BAND],
    ...overrides,
  };
}

test("blur boxes map source fractions through fit, crop and position", () => {
  const [box] = blurBoxes(clip(), { width: 720, height: 1280 }, CANVAS);
  // Before widening the band sits at 108 / 1248 / 864 x 169 on the canvas.
  expect(box!.sigma).toBeCloseTo(0.2 * 0.0878 * 1920, 0);
  expect(box!.left).toBeCloseTo(108 - box!.sigma, 0);
  expect(box!.top).toBeCloseTo(1248 - box!.sigma, 0);
  expect(box!.width).toBeCloseTo(864 + 2 * box!.sigma, 0);
  expect(box!.height).toBeCloseTo(0.0878 * 1920 + 2 * box!.sigma, 0);
});

test("a scaled clip keeps the canvas blur strength", () => {
  const [box] = blurBoxes(clip({ position: { x: 0, y: 0, scale: 0.5 } }), { width: 720, height: 1280 }, CANVAS);
  // Local pixels shrink by the scale on the canvas, so sigma x scale must reach the floor.
  expect(box!.sigma * 0.5).toBeGreaterThanOrEqual(24 - 1e-9);
});

test("a small band still blurs at the floor", () => {
  const [box] = blurBoxes(clip({ blur_regions: [{ ...BAND, h: 0.02 }] }), { width: 720, height: 1280 }, CANVAS);
  expect(box!.sigma).toBeCloseTo(24, 5);
});

test("blur falls back to the clip frame when the asset size is unknown", () => {
  const [box] = blurBoxes(clip(), undefined, CANVAS);
  expect(box!.left).toBeCloseTo(108 - box!.sigma, 0);
  expect(box!.top).toBeCloseTo(1248 - box!.sigma, 0);
});

test("a contain clip letterboxes the band into the drawn picture", () => {
  // A 16:9 source drawn contain on 9:16 is 1080 x 607.5, centred at y 656.25.
  const [box] = blurBoxes(clip({ fit: "contain" }), { width: 1920, height: 1080 }, CANVAS);
  expect(box!.top + box!.sigma).toBeCloseTo(656.25 + 0.65 * 607.5, 0);
});

test("a window is relative to the clip's own trim", () => {
  const [box] = blurBoxes(
    clip({ source_from_frame: 60, blur_regions: [{ ...BAND, from_frame: 90, to_frame: 150 }] }),
    { width: 720, height: 1280 },
    CANVAS,
  );
  expect([box!.from, box!.to]).toEqual([30, 90]);
});

test("a window wholly before the clip's trim draws nothing", () => {
  // A split or trim past the window's end must not flash a one-frame blur at the start.
  const boxes = blurBoxes(
    clip({ source_from_frame: 90, blur_regions: [{ ...BAND, from_frame: 30, to_frame: 90 }] }),
    { width: 720, height: 1280 },
    CANVAS,
  );
  expect(boxes).toEqual([]);
});
