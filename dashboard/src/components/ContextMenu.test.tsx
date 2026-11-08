/// <reference types="bun-types" />

import { afterEach, expect, mock, test } from "bun:test";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

import { useContextMenu, type MenuEntry } from "./ContextMenu";

afterEach(cleanup);

function Harness({ entries }: { entries: MenuEntry[] }) {
  const menu = useContextMenu();
  return (
    <div>
      <button type="button" {...menu.bind(() => entries)}>
        Owner
      </button>
      <p>Outside</p>
      {menu.element}
    </div>
  );
}

const item = (id: string, extra: Partial<Extract<MenuEntry, { kind: "item" }>> = {}): MenuEntry => ({
  kind: "item",
  id,
  label: id,
  onSelect: () => {},
  ...extra,
});

test("right click opens a menu at the pointer", () => {
  render(<Harness entries={[item("Split"), item("Delete")]} />);
  fireEvent.contextMenu(screen.getByText("Owner"), { clientX: 40, clientY: 50 });
  const menu = screen.getByRole("menu");
  expect(menu.style.left).toBe("40px");
  expect(document.activeElement).toBe(screen.getAllByRole("menuitem")[0]!);
});

test("Shift+F10 opens it on the focused element", () => {
  render(<Harness entries={[item("Split")]} />);
  fireEvent.keyDown(screen.getByText("Owner"), { key: "F10", shiftKey: true });
  expect(screen.getByRole("menu")).toBeTruthy();
});

test("Escape, an outside pointer down and a chosen item close it", () => {
  const chosen = mock(() => {});
  render(<Harness entries={[item("Split", { onSelect: chosen })]} />);
  const owner = screen.getByText("Owner");

  fireEvent.contextMenu(owner, { clientX: 1, clientY: 1 });
  fireEvent.keyDown(screen.getByRole("menu"), { key: "Escape" });
  expect(screen.queryByRole("menu")).toBeNull();

  fireEvent.contextMenu(owner, { clientX: 1, clientY: 1 });
  fireEvent.pointerDown(screen.getByText("Outside"));
  expect(screen.queryByRole("menu")).toBeNull();

  fireEvent.contextMenu(owner, { clientX: 1, clientY: 1 });
  fireEvent.click(screen.getByRole("menuitem", { name: "Split" }));
  expect(screen.queryByRole("menu")).toBeNull();
  expect(chosen).toHaveBeenCalledTimes(1);
});

test("arrows move between enabled items and Enter acts", () => {
  const second = mock(() => {});
  render(<Harness entries={[item("First"), item("Off", { disabled: true, reason: "No" }), item("Second", { onSelect: second })]} />);
  fireEvent.contextMenu(screen.getByText("Owner"), { clientX: 1, clientY: 1 });
  const menu = screen.getByRole("menu");
  fireEvent.keyDown(menu, { key: "ArrowDown" });
  expect(document.activeElement).toBe(screen.getByRole("menuitem", { name: "Second" }));
  fireEvent.keyDown(menu, { key: "Enter" });
  expect(second).toHaveBeenCalledTimes(1);
});

test("a disabled entry shows why and does nothing", () => {
  const never = mock(() => {});
  render(<Harness entries={[item("Split", { disabled: true, reason: "The playhead is outside this clip", onSelect: never })]} />);
  fireEvent.contextMenu(screen.getByText("Owner"), { clientX: 1, clientY: 1 });
  const entry = screen.getByRole("menuitem", { name: "Split" });
  expect(entry.getAttribute("aria-disabled")).toBe("true");
  expect(entry.getAttribute("title")).toBe("The playhead is outside this clip");
  fireEvent.click(entry);
  expect(never).not.toHaveBeenCalled();
});

test("a group lists its items under its label", () => {
  render(
    <Harness
      entries={[{ kind: "group", id: "move", label: "Move to track", entries: [item("B-roll"), item("Overlay")] }]}
    />,
  );
  fireEvent.contextMenu(screen.getByText("Owner"), { clientX: 1, clientY: 1 });
  const group = screen.getByRole("group", { name: "Move to track" });
  expect(group.querySelectorAll('[role="menuitem"]').length).toBe(2);
});

test("a menu near the corner stays inside the viewport", () => {
  const width = window.innerWidth;
  const height = window.innerHeight;
  Object.assign(window, { innerWidth: 300, innerHeight: 200 });
  const measure = HTMLElement.prototype.getBoundingClientRect;
  HTMLElement.prototype.getBoundingClientRect = function () {
    return this.getAttribute("role") === "menu"
      ? ({ width: 160, height: 120, top: 0, left: 0, right: 160, bottom: 120, x: 0, y: 0, toJSON: () => ({}) } as DOMRect)
      : measure.call(this);
  };
  try {
    render(<Harness entries={[item("Split")]} />);
    fireEvent.contextMenu(screen.getByText("Owner"), { clientX: 290, clientY: 190 });
    const menu = screen.getByRole("menu");
    expect(parseFloat(menu.style.left)).toBeLessThanOrEqual(140);
    expect(parseFloat(menu.style.top)).toBeLessThanOrEqual(80);
  } finally {
    HTMLElement.prototype.getBoundingClientRect = measure;
    Object.assign(window, { innerWidth: width, innerHeight: height });
  }
});

test("a long touch press opens it, a short one does not", async () => {
  render(<Harness entries={[item("Split")]} />);
  const owner = screen.getByText("Owner");

  fireEvent.pointerDown(owner, { pointerType: "touch", clientX: 5, clientY: 5 });
  fireEvent.pointerUp(owner);
  await new Promise((done) => setTimeout(done, 550));
  expect(screen.queryByRole("menu")).toBeNull();

  fireEvent.pointerDown(owner, { pointerType: "touch", clientX: 5, clientY: 5 });
  await new Promise((done) => setTimeout(done, 550));
  expect(screen.getByRole("menu")).toBeTruthy();
});

// Final review 2026-11-08 #7.
test("a menu whose entries are all disabled still closes on Escape", () => {
  render(<Harness entries={[item("Close this gap", { disabled: true, reason: "There is no gap here" })]} />);
  fireEvent.contextMenu(screen.getByText("Owner"), { clientX: 1, clientY: 1 });
  const menu = screen.getByRole("menu");
  expect(menu.contains(document.activeElement)).toBe(true);
  fireEvent.keyDown(document.activeElement!, { key: "Escape" });
  expect(screen.queryByRole("menu")).toBeNull();
});
