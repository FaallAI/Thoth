/// <reference types="bun-types" />

import { afterEach, expect, mock, test } from "bun:test";
import { cleanup, fireEvent, screen } from "@testing-library/react";

import { render } from "@/test-render";
import { PasteTextDialog } from "./PasteTextDialog";

afterEach(cleanup);

// Spec 2026-11-08 §6: pasted text goes where the person picks, and nowhere until they do.
const targets = [
  { target: "new_text" as const },
  { target: "replace_text" as const, disabled: true, reason: "Select a text clip first" },
  { target: "new_caption" as const },
  { target: "replace_caption" as const, disabled: true, reason: "Select a caption clip first" },
];

test("it names the four places, with the ones that do not apply disabled and explained", () => {
  render(<PasteTextDialog text="Hello" targets={targets} onPick={() => {}} onClose={() => {}} />);
  const dialog = screen.getByRole("dialog", { name: "Paste text" });
  expect(dialog.textContent).toContain("Hello");
  const names = ["New text clip", "Replace the selected text", "New caption", "Replace the caption text"];
  for (const name of names) expect(screen.getByRole("button", { name })).toBeDefined();
  // Final review 2026-11-08, Important 4: a place that does not apply stays reachable and says why in words.
  const replace = screen.getByRole("button", { name: "Replace the selected text" });
  expect(replace.getAttribute("aria-disabled")).toBe("true");
  expect(replace.textContent).toContain("Select a text clip first");
  expect(replace.getAttribute("aria-describedby")).toBeTruthy();
});

test("nothing is placed until a pick, and a pick names its place", () => {
  const onPick = mock(() => {});
  render(<PasteTextDialog text="Hello" targets={targets} onPick={onPick} onClose={() => {}} />);
  expect(onPick).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "New caption" }));
  expect(onPick).toHaveBeenCalledWith("new_caption");
});

test("Escape cancels", () => {
  const onClose = mock(() => {});
  render(<PasteTextDialog text="Hello" targets={targets} onPick={() => {}} onClose={onClose} />);
  fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });
  expect(onClose).toHaveBeenCalledTimes(1);
});

test("a place that does not apply does nothing when chosen", () => {
  const onPick = mock(() => {});
  render(<PasteTextDialog text="Hello" targets={targets} onPick={onPick} onClose={() => {}} />);
  fireEvent.click(screen.getByRole("button", { name: "Replace the selected text" }));
  expect(onPick).not.toHaveBeenCalled();
});

test("closing returns focus to where it was", () => {
  const before = document.body.appendChild(document.createElement("button"));
  before.focus();
  const view = render(<PasteTextDialog text="Hello" targets={targets} onPick={() => {}} onClose={() => {}} />);
  expect(document.activeElement).not.toBe(before);
  view.unmount();
  expect(document.activeElement).toBe(before);
  before.remove();
});

// Carried Tier 2 minor (operator, 2026-11-09): Tab stays inside the chooser.
test("Tab from the last place wraps to the first, and Shift+Tab back", () => {
  render(<PasteTextDialog text="Hello" targets={targets} onPick={() => {}} onClose={() => {}} />);
  const dialog = screen.getByRole("dialog", { name: "Paste text" });
  const buttons = Array.from(dialog.querySelectorAll("button"));
  const [first, last] = [buttons[0]!, buttons.at(-1)!];
  last.focus();
  expect(fireEvent.keyDown(last, { key: "Tab" })).toBe(false);
  expect(document.activeElement).toBe(first);
  expect(fireEvent.keyDown(first, { key: "Tab", shiftKey: true })).toBe(false);
  expect(document.activeElement).toBe(last);
});

test("Tab between places is left to the browser", () => {
  render(<PasteTextDialog text="Hello" targets={targets} onPick={() => {}} onClose={() => {}} />);
  const first = screen.getByRole("dialog", { name: "Paste text" }).querySelector("button")!;
  first.focus();
  expect(fireEvent.keyDown(first, { key: "Tab" })).toBe(true);
});
