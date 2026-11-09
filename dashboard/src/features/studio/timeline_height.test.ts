/// <reference types="bun-types" />

import { afterEach, expect, test } from "bun:test";

import {
  clampTimelineHeight,
  maxTimelineHeight,
  readTimelineHeight,
  saveTimelineHeight,
  timelineRows,
} from "./timeline_height";

afterEach(() => localStorage.removeItem("thoth.studio.timelineHeight"));

test("the timeline keeps its limits", () => {
  expect(clampTimelineHeight(100, 844)).toBe(150);
  expect(clampTimelineHeight(9000, 844)).toBe(844 - 8 - 240);
  expect(clampTimelineHeight(400, 844)).toBe(400);
});

test("a window too short for both rows still gives the smallest timeline", () => {
  expect(maxTimelineHeight(300)).toBe(150);
});

test("a stored height is read back, and anything unusable is the default", () => {
  saveTimelineHeight(300);
  expect(readTimelineHeight()).toBe(300);
  for (const bad of ["abc", "-5", "0", "NaN"]) {
    localStorage.setItem("thoth.studio.timelineHeight", bad);
    expect(readTimelineHeight()).toBe(392);
  }
});

test("storage that throws is the default and never an error", () => {
  const original = Storage.prototype.getItem;
  Storage.prototype.getItem = () => {
    throw new Error("blocked");
  };
  try {
    expect(readTimelineHeight()).toBe(392);
  } finally {
    Storage.prototype.getItem = original;
  }
});

test("storage that refuses a write is not an error", () => {
  const original = Storage.prototype.setItem;
  Storage.prototype.setItem = () => {
    throw new Error("full");
  };
  try {
    expect(() => saveTimelineHeight(300)).not.toThrow();
  } finally {
    Storage.prototype.setItem = original;
  }
});

test("rows let CSS fit the height to the window", () => {
  expect(timelineRows(300)).toBe("minmax(240px,1fr) 8px minmax(150px,300px)");
});
