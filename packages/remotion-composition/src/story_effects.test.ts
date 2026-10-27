/// <reference types="bun-types" />
import { expect, test } from "bun:test";

import { contentBox, emphasisBox, motionTransform } from "./story_effects";

test("no motion leaves the clip where it is on every frame", () => {
  for (const frame of [0, 30, 59]) expect(motionTransform("none", frame, 60)).toEqual({ scale: 1, translateX: 0 });
});

test("slow zoom grows linearly from 1.00 to 1.08 across the clip", () => {
  expect(motionTransform("slow_zoom", 0, 61)).toEqual({ scale: 1, translateX: 0 });
  expect(motionTransform("slow_zoom", 30, 61).scale).toBeCloseTo(1.04, 10);
  expect(motionTransform("slow_zoom", 60, 61).scale).toBeCloseTo(1.08, 10);
});

test("pan travels from -3% to +3% of the canvas width", () => {
  expect(motionTransform("pan", 0, 61).translateX).toBeCloseTo(-0.03, 10);
  expect(motionTransform("pan", 30, 61).translateX).toBeCloseTo(0, 10);
  expect(motionTransform("pan", 60, 61)).toEqual({ scale: 1, translateX: 0.03 });
});

test("a one-frame clip does not divide by zero", () => {
  expect(motionTransform("slow_zoom", 0, 1)).toEqual({ scale: 1, translateX: 0 });
});

test("a contained 4:5 card fills the 9:16 frame's width only", () => {
  const box = contentBox("contain", { width: 1080, height: 1350 }, { width: 1080, height: 1920 });
  expect(box.width).toBe(1);
  expect(box.height).toBeCloseTo(1350 / 1920, 10);
  expect(contentBox("cover", { width: 1080, height: 1350 }, { width: 1080, height: 1920 })).toEqual({
    width: 1,
    height: 1,
  });
});

test("the emphasis box follows the stored placement and the motion", () => {
  const box = emphasisBox({ x: 0, y: -0.24, scale: 0.76 }, { width: 1, height: 0.5 }, { scale: 1, translateX: 0 });
  expect(box.left).toBeCloseTo(0.12, 10);
  expect(box.width).toBeCloseTo(0.76, 10);
  expect(box.top).toBeCloseTo(0.26 - 0.19, 10);
  expect(box.height).toBeCloseTo(0.38, 10);

  const panned = emphasisBox(null, { width: 1, height: 1 }, { scale: 1.08, translateX: 0.03 });
  expect(panned.left).toBeCloseTo(0.5 + 0.03 - 0.54, 10);
  expect(panned.width).toBeCloseTo(1.08, 10);
});
