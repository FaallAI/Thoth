/// <reference types="bun-types" />

import { afterEach, expect, test } from "bun:test";
import { useState } from "react";
import { cleanup, fireEvent, screen, within } from "@testing-library/react";

import { render } from "@/test-render";
import { ShortcutsDialog } from "./ShortcutsDialog";
import { useStudioShortcuts } from "./studio_keys";

afterEach(cleanup);

const undone: string[] = [];

function Harness() {
  const [open, setOpen] = useState(false);
  useStudioShortcuts({ undo: () => undone.push("undo"), redo: () => {}, shortcuts: () => setOpen(true), enabled: true });
  return (
    <>
      <input aria-label="Heading" />
      <ShortcutsDialog open={open} onClose={() => setOpen(false)} />
    </>
  );
}

test("? and Ctrl+/ open the list, and Escape closes it", () => {
  render(<Harness />);
  fireEvent.keyDown(document.body, { key: "?" });
  const dialog = screen.getByRole("dialog", { name: "Keyboard shortcuts" });
  fireEvent.keyDown(dialog, { key: "Escape" });
  expect(screen.queryByRole("dialog")).toBeNull();
  fireEvent.keyDown(document.body, { key: "/", ctrlKey: true });
  expect(screen.getByRole("dialog", { name: "Keyboard shortcuts" })).toBeTruthy();
});

test("? typed in a field stays in the field", () => {
  render(<Harness />);
  fireEvent.keyDown(screen.getByLabelText("Heading"), { key: "?" });
  expect(screen.queryByRole("dialog")).toBeNull();
});

test("the list names each action with its keys, in groups", () => {
  render(<ShortcutsDialog open onClose={() => {}} />);
  const editing = screen.getByRole("table", { name: "Editing" });
  const ripple = within(editing).getByRole("row", { name: /Ripple delete/ });
  expect(within(ripple).getByText("Shift+Delete")).toBeTruthy();
  for (const group of ["Playback", "View", "Studio"]) expect(screen.getByRole("table", { name: group })).toBeTruthy();
});

test("the list reads in Indonesian too", () => {
  render(<ShortcutsDialog open onClose={() => {}} />, { locale: "id" });
  expect(screen.getByRole("dialog", { name: "Pintasan keyboard" })).toBeTruthy();
});

// Final review 2026-11-08 #3: Ctrl+Z inside an open dialog does not undo the draft behind it.
test("Ctrl+Z inside the open list does not undo the draft", () => {
  undone.length = 0;
  render(<Harness />);
  fireEvent.keyDown(document.body, { key: "?" });
  fireEvent.keyDown(screen.getByRole("dialog", { name: "Keyboard shortcuts" }), { key: "z", ctrlKey: true });
  expect(undone).toEqual([]);
});
