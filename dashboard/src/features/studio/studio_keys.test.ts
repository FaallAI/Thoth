/// <reference types="bun-types" />

import { expect, test } from "bun:test";

import { isTypingTarget, SHORTCUTS, shuttleRate, timelineKey } from "./studio_keys";

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

// Tier 2 (spec 2026-11-08 §6): J, K and L.
test("timelineKey maps J, K and L, without modifiers only", () => {
  expect([key("j"), key("k"), key("l"), key("L")]).toEqual(["shuttle_back", "shuttle_stop", "shuttle_forward", "shuttle_forward"]);
  expect(key("l", { ctrlKey: true })).toBeNull();
  expect(SHORTCUTS.map((entry) => entry.action)).toEqual(expect.arrayContaining(["shuttle_back", "shuttle_stop", "shuttle_forward"]));
});

test("L plays, and each L while playing doubles the rate up to 4", () => {
  expect(shuttleRate(false, 1)).toBe(1);
  expect(shuttleRate(true, 1)).toBe(2);
  expect(shuttleRate(true, 2)).toBe(4);
  expect(shuttleRate(true, 4)).toBe(4);
  expect(shuttleRate(false, 4)).toBe(1);
});

// Tier 1 review leftovers (2026-11-08): the shortcut list names every key the Studio answers.
test("the shortcut list includes the second keys and the pointer shortcuts", () => {
  const keys = SHORTCUTS.map((entry) => entry.keys).join(" | ");
  for (const shown of ["Backspace", "Ctrl+Shift+Z", "Ctrl+/", "Ctrl+wheel", "Shift+F10", "Ctrl+A", "Ctrl+C", "Ctrl+V", "Ctrl+D", "J", "K", "L"]) {
    expect(keys).toContain(shown);
  }
});

test("the shortcut list names the slip gesture (Tier 3a)", () => {
  expect(SHORTCUTS.find((entry) => entry.action === "slip_drag")?.keys).toBe("Alt+drag");
});

test("the shortcut list names the roll gesture (Tier 3a)", () => {
  expect(SHORTCUTS.find((entry) => entry.action === "roll_drag")?.keys).toBe("Alt+drag");
});
