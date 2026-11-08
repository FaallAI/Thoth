/// <reference types="bun-types" />

import { expect, test } from "bun:test";

import { isTypingTarget, SHORTCUTS, timelineKey } from "./studio_keys";

const make = (html: string) => {
  const host = document.createElement("div");
  host.innerHTML = html;
  return host.firstElementChild!;
};

test("isTypingTarget is true only where a key types", () => {
  expect(isTypingTarget(make('<input type="text">'))).toBe(true);
  expect(isTypingTarget(make("<input>"))).toBe(true);
  expect(isTypingTarget(make("<textarea></textarea>"))).toBe(true);
  expect(isTypingTarget(make("<select></select>"))).toBe(true);
  expect(isTypingTarget(make('<div contenteditable="true"></div>'))).toBe(true);
  expect(isTypingTarget(make('<input type="checkbox">'))).toBe(false);
  expect(isTypingTarget(make("<button></button>"))).toBe(false);
  expect(isTypingTarget(null)).toBe(false);
});

const key = (key: string, mods: Partial<{ ctrlKey: boolean; metaKey: boolean; shiftKey: boolean; altKey: boolean }> = {}) =>
  timelineKey({ key, ctrlKey: false, metaKey: false, shiftKey: false, altKey: false, ...mods });

test("timelineKey maps the agreed shortcuts", () => {
  expect(key("Delete")).toBe("delete");
  expect(key("Backspace")).toBe("delete");
  expect(key("Delete", { shiftKey: true })).toBe("ripple_delete");
  expect(key("s")).toBe("split");
  expect(key("S")).toBe("split");
  expect(key("s", { ctrlKey: true })).toBeNull();
  expect(key(" ")).toBe("play");
  expect(key("Home")).toBe("start");
  expect(key("End")).toBe("end");
  expect(key("ArrowLeft")).toBe("frame_back");
  expect(key("ArrowRight")).toBe("frame_forward");
  expect(key("ArrowLeft", { shiftKey: true })).toBe("second_back");
  expect(key("ArrowRight", { shiftKey: true })).toBe("second_forward");
  expect(key("=", { ctrlKey: true })).toBe("zoom_in");
  expect(key("+", { ctrlKey: true })).toBe("zoom_in");
  expect(key("-", { ctrlKey: true })).toBe("zoom_out");
  expect(key("0", { ctrlKey: true })).toBe("zoom_fit");
  expect(key("Escape")).toBe("clear");
  expect(key("x")).toBeNull();
});

test("the shortcut list names every Timeline key it maps", () => {
  const actions: string[] = SHORTCUTS.map((entry) => entry.action);
  for (const action of ["delete", "ripple_delete", "split", "play", "zoom_fit", "undo", "redo", "shortcuts"]) {
    expect(actions).toContain(action);
  }
});
