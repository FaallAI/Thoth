/// <reference types="bun-types" />

import { expect, test } from "bun:test";

import { kineticGroups, markBox, markWindowOpen } from "./effects";

const FULL = { left: 0, top: 0, width: 1, height: 1 };
const STILL = { scale: 1, translateX: 0, translateY: 0 };
const MARK = { kind: "box" as const, x: 0.2, y: 0.2, w: 0.4, h: 0.2, from_frame: 60, to_frame: 90 };

test("a mark opens in its source window at speed 2", () => {
  const clip = { source_from_frame: 0, speed: 2 as const };
  expect(markWindowOpen(MARK, clip, 29)).toBe(false);
  expect(markWindowOpen(MARK, clip, 30)).toBe(true);
  expect(markWindowOpen(MARK, clip, 44)).toBe(true);
  expect(markWindowOpen(MARK, clip, 45)).toBe(false);
});

test("a mark follows the clip's source start", () => {
  expect(markWindowOpen(MARK, { source_from_frame: 50 }, 10)).toBe(true);
  expect(markWindowOpen(MARK, { source_from_frame: 50 }, 40)).toBe(false);
});

test("a mark maps through the crop into the visible media", () => {
  const box = markBox(MARK, { left: 0.2, top: 0, width: 0.5, height: 1 }, { width: 1, height: 1 }, null, STILL)!;
  expect(box.left).toBeCloseTo(0);
  expect(box.width).toBeCloseTo(0.8);
  expect(box.top).toBeCloseTo(0.2);
  expect(box.height).toBeCloseTo(0.2);
});

test("a mark outside the crop is not drawn", () => {
  const away = { ...MARK, x: 0.0, w: 0.1 };
  expect(markBox(away, { left: 0.5, top: 0, width: 0.5, height: 1 }, { width: 1, height: 1 }, null, STILL)).toBeNull();
});

test("a mark partly outside the crop is cut at its edge", () => {
  const box = markBox({ ...MARK, x: 0.6, w: 0.4 }, { left: 0, top: 0, width: 0.8, height: 1 }, { width: 1, height: 1 }, null, STILL)!;
  expect(box.left).toBeCloseTo(0.75);
  expect(box.left + box.width).toBeCloseTo(1);
});

test("a mark sits on a placed and moved clip", () => {
  const box = markBox(MARK, FULL, { width: 1, height: 1 }, { x: 0.1, y: 0, scale: 0.5 }, { scale: 2, translateX: 0, translateY: 0.1 })!;
  // The media spans the whole canvas again (0.5 x 2), centred at 0.6 across and 0.6 down.
  expect(box.left).toBeCloseTo(0.3);
  expect(box.top).toBeCloseTo(0.3);
  expect(box.width).toBeCloseTo(0.4);
});

test("an arrow outside the crop is not drawn", () => {
  const arrow = { kind: "arrow" as const, x: 0.1, y: 0.5, w: 0, h: 0, from_frame: 0, to_frame: 10 };
  expect(markBox(arrow, { left: 0.5, top: 0, width: 0.5, height: 1 }, { width: 1, height: 1 }, null, STILL)).toBeNull();
});

const word = (text: string, from: number) => ({ text, from_frame: from, duration_in_frames: 5 });

test("kinetic groups break at four words and at punctuation", () => {
  const words = ["Indonesia", "baru", "aja", "nge-unlock", "level", "terendah.", "Kok", "bisa", "ya?"].map((text, i) => word(text, i * 5));
  expect(kineticGroups(words).map((group) => group.text)).toEqual([
    "Indonesia baru aja nge-unlock",
    "level terendah.",
    "Kok bisa ya?",
  ]);
  expect(kineticGroups(words)[1]).toEqual({ from: 20, to: 30, text: "level terendah." });
});

test("a lone last word joins the group before it", () => {
  const words = ["satu", "dua", "tiga", "empat", "lima"].map((text, i) => word(text, i * 5));
  expect(kineticGroups(words).map((group) => group.text)).toEqual(["satu dua tiga empat lima"]);
});

test("kinetic one-word cue is one group", () => {
  expect(kineticGroups([word("Selamat", 0)])).toEqual([{ from: 0, to: 5, text: "Selamat" }]);
});
