/// <reference types="bun-types" />

import { afterEach, expect, mock, test } from "bun:test";
import { cleanup, fireEvent, screen } from "@testing-library/react";

import { render } from "@/test-render";

import { TimelineDivider } from "./TimelineDivider";

afterEach(cleanup);

function mount(height = 392) {
  const onResize = mock((_height: number) => {});
  const onCommit = mock((_height: number) => {});
  const workstation = { getBoundingClientRect: () => ({ height: 844 }) } as HTMLElement;
  const view = render(
    <TimelineDivider height={height} workstation={() => workstation} onResize={onResize} onCommit={onCommit} />,
  );
  return { onResize, onCommit, divider: screen.getByRole("separator", { name: "Resize timeline" }), ...view };
}

test("arrow keys move it 16 px, 64 with Shift", () => {
  const { divider, onCommit } = mount();
  fireEvent.keyDown(divider, { key: "ArrowUp" });
  fireEvent.keyDown(divider, { key: "ArrowDown" });
  fireEvent.keyDown(divider, { key: "ArrowUp", shiftKey: true });
  expect(onCommit.mock.calls.map(([height]) => height)).toEqual([408, 376, 456]);
});

test("Home and End go to the limits", () => {
  const { divider, onCommit } = mount();
  fireEvent.keyDown(divider, { key: "Home" });
  fireEvent.keyDown(divider, { key: "End" });
  expect(onCommit.mock.calls.map(([height]) => height)).toEqual([150, 596]);
});

test("keys on the divider do not reach the window", () => {
  const { divider } = mount();
  const spy = mock(() => {});
  window.addEventListener("keydown", spy);
  try {
    fireEvent.keyDown(divider, { key: "Home" });
    expect(spy).not.toHaveBeenCalled();
    fireEvent.keyDown(divider, { key: "x" });
    expect(spy).toHaveBeenCalledTimes(1);
  } finally {
    window.removeEventListener("keydown", spy);
  }
});

test("a drag previews, then commits once", () => {
  const { divider, onResize, onCommit } = mount();
  fireEvent.pointerDown(divider, { clientY: 500, button: 0 });
  fireEvent.pointerMove(window, { clientY: 480 });
  expect(onResize).toHaveBeenLastCalledWith(412);
  expect(onCommit).not.toHaveBeenCalled();
  fireEvent.pointerUp(window, { clientY: 480 });
  expect(onCommit.mock.calls).toEqual([[412]]);
});

test("a press without a move commits nothing", () => {
  const { divider, onCommit } = mount();
  fireEvent.pointerDown(divider, { clientY: 500, button: 0 });
  fireEvent.pointerUp(window, { clientY: 500 });
  expect(onCommit).not.toHaveBeenCalled();
});

test("a cancelled pointer commits what it last previewed", () => {
  const { divider, onCommit } = mount();
  fireEvent.pointerDown(divider, { clientY: 500, button: 0 });
  fireEvent.pointerMove(window, { clientY: 490 });
  fireEvent.pointerCancel(window);
  expect(onCommit.mock.calls).toEqual([[402]]);
});

test("a drag starts from the height on screen", () => {
  const { divider, onResize } = mount(2000);
  fireEvent.pointerDown(divider, { clientY: 500, button: 0 });
  fireEvent.pointerMove(window, { clientY: 490 });
  expect(onResize).toHaveBeenLastCalledWith(596);
  fireEvent.pointerMove(window, { clientY: 510 });
  expect(onResize).toHaveBeenLastCalledWith(586);
});

test("double-click returns to the default", () => {
  const { divider, onCommit } = mount(500);
  fireEvent.doubleClick(divider);
  expect(onCommit.mock.calls).toEqual([[392]]);
});

test("unmounting mid-drag stops listening", () => {
  const { divider, onResize, unmount } = mount();
  fireEvent.pointerDown(divider, { clientY: 500, button: 0 });
  unmount();
  fireEvent.pointerMove(window, { clientY: 400 });
  expect(onResize).not.toHaveBeenCalled();
});

test("it says its size", () => {
  const { divider } = mount();
  expect(divider.getAttribute("aria-orientation")).toBe("horizontal");
  expect(divider.getAttribute("aria-valuenow")).toBe("392");
  expect(divider.getAttribute("aria-valuemin")).toBe("150");
  expect(divider.getAttribute("aria-valuemax")).toBe("596");
  expect(divider.getAttribute("aria-controls")).toBe("studio-timeline");
  expect(divider.getAttribute("tabindex")).toBe("0");
});
