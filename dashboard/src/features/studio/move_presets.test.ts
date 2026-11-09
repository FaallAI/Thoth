/// <reference types="bun-types" />

import { expect, test } from "bun:test";

import type { Ease } from "@thoth/remotion-composition";

import { movePreset } from "./move_presets";

const at = (frame: number, scale: number, ease: Ease, x = 0, y = 0) => ({ frame, scale, x, y, ease });

test("push in grows 12% across the clip", () => {
  expect(movePreset("push_in", 90, 30)).toEqual([at(0, 1, "linear"), at(89, 1.12, "linear")]);
});

test("pan across travels from 6% right to 6% left at 115%", () => {
  expect(movePreset("pan_across", 90, 30)).toEqual([at(0, 1.15, "linear", 0.06), at(89, 1.15, "linear", -0.06)]);
});

test("scroll down travels a tall picture from its top to its bottom at 160%", () => {
  expect(movePreset("scroll_down", 90, 30)).toEqual([at(0, 1.6, "ease_in_out", 0, 0.3), at(89, 1.6, "ease_in_out", 0, -0.3)]);
});

test("pull out starts 20% larger and eases back", () => {
  expect(movePreset("pull_out", 90, 30)).toEqual([at(0, 1.2, "ease_out"), at(89, 1, "ease_out")]);
});

test("punch in jumps to 135% in eight frames at the playhead and holds", () => {
  expect(movePreset("punch_in", 90, 30, 40)).toEqual([at(39, 1, "ease_out"), at(48, 1.35, "hold")]);
});

test("punch in joins the moves already there, replacing a keyframe on the same frame", () => {
  const existing = [at(0, 1, "linear"), at(39, 1.1, "linear"), at(80, 1.1, "linear")];
  expect(movePreset("punch_in", 90, 30, 40, existing)).toEqual([
    at(0, 1, "linear"),
    at(39, 1, "ease_out"),
    at(48, 1.35, "hold"),
    at(80, 1.1, "linear"),
  ]);
});

test("punch in near the end stays inside the clip", () => {
  expect(movePreset("punch_in", 90, 30, 88)).toEqual([at(87, 1, "ease_out"), at(89, 1.35, "hold")]);
});

test("punch in at the clip's first frame starts there", () => {
  expect(movePreset("punch_in", 90, 30, 0)).toEqual([at(0, 1, "ease_out"), at(8, 1.35, "hold")]);
});
