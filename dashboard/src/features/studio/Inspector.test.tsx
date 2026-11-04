/// <reference types="bun-types" />

import { afterEach, expect, mock, test } from "bun:test";
import { cleanup, fireEvent, screen } from "@testing-library/react";
import { render } from "@/test-render";
import { Inspector } from "./Inspector";
import type { EditableTextClip } from "./editor_state";

afterEach(cleanup);

const clip = {
  kind: "text",
  clip_id: "clip_001",
  heading: "Original heading",
  body: "Original body",
  ownership: "ai_managed",
} as EditableTextClip;

function renderInspector(frames: number) {
  const onDurationChange = mock((_sceneId: string, _frames: number) => {});
  const view = render(
    <Inspector
      scene={{ scene_id: "scene_001", duration_in_frames: frames }}
      clip={clip}
      fps={30}
      onTextChange={() => {}}
      onOwnershipChange={() => {}}
      onDurationChange={onDurationChange}
    />,
  );
  const duration = screen.getByLabelText("Duration (seconds)") as HTMLInputElement;
  return { onDurationChange, duration, view };
}

test("shows the duration in seconds and leaves an untouched duration alone", () => {
  const { onDurationChange, duration } = renderInspector(151);
  expect(duration.value).toBe("5.033");
  fireEvent.blur(duration);
  fireEvent.keyDown(duration, { key: "Enter" });
  expect(onDurationChange).toHaveBeenCalledTimes(0);
});

test("commits an explicit duration in frames on blur and on Enter, not per keystroke", () => {
  const { onDurationChange, duration } = renderInspector(150);
  fireEvent.change(duration, { target: { value: "5.033" } });
  expect(onDurationChange).toHaveBeenCalledTimes(0);
  fireEvent.blur(duration);
  expect(onDurationChange.mock.calls).toEqual([["scene_001", 151]]);

  fireEvent.change(duration, { target: { value: "6" } });
  fireEvent.keyDown(duration, { key: "Enter" });
  expect(onDurationChange.mock.calls[1]).toEqual(["scene_001", 180]);
});

test("keeps invalid input with an associated inline error and commits nothing", () => {
  const { onDurationChange, duration } = renderInspector(150);
  for (const value of ["0", "abc", ""]) {
    fireEvent.change(duration, { target: { value } });
    fireEvent.blur(duration);
    expect(duration.value).toBe(value);
    const error = globalThis.document.getElementById(duration.getAttribute("aria-describedby") ?? "");
    expect(error?.textContent).toBe("Enter a duration greater than zero seconds.");
    expect(duration.getAttribute("aria-invalid")).toBe("true");
  }
  expect(onDurationChange).toHaveBeenCalledTimes(0);

  fireEvent.change(duration, { target: { value: "4" } });
  fireEvent.blur(duration);
  expect(duration.hasAttribute("aria-describedby")).toBe(false);
  expect(onDurationChange.mock.calls).toEqual([["scene_001", 120]]);
});

test("follows a duration the document changes elsewhere, such as undo", () => {
  const { duration, view } = renderInspector(150);
  view.rerender(
    <Inspector
      scene={{ scene_id: "scene_001", duration_in_frames: 151 }}
      clip={clip}
      fps={30}
      onTextChange={() => {}}
      onOwnershipChange={() => {}}
      onDurationChange={() => {}}
    />,
  );
  expect(duration.value).toBe("5.033");
});

test("the scene heading is clamped to two lines with its full text on hover, and Edit goes to the field", () => {
  // Studio shell v2 (spec 2026-11-01, goal 5): a long heading no longer fills the inspector.
  const long = "Warga Palangka Raya masih bertahan di tengah kabut pekat, banyak yang menunggu bantuan sejak pekan lalu";
  render(
    <Inspector
      scene={{ scene_id: "scene_001", duration_in_frames: 150 }}
      clip={{ ...clip, heading: long }}
      fps={30}
      sceneIndex={0}
      sceneCount={1}
      onTextChange={() => {}}
      onOwnershipChange={() => {}}
      onDurationChange={() => {}}
    />,
  );

  const heading = screen.getByRole("heading", { level: 2, name: long });
  expect(heading.className).toContain("line-clamp-2");
  expect(heading.getAttribute("title")).toBe(long);
  fireEvent.click(screen.getByRole("button", { name: "Edit heading" }));
  expect(document.activeElement).toBe(screen.getByLabelText("Heading"));
});

test("the scene fields speak Indonesian", () => {
  const { container } = render(
    <Inspector scene={{ scene_id: "scene_001", duration_in_frames: 150 }} clip={clip} fps={30} onTextChange={() => {}} onOwnershipChange={() => {}} onDurationChange={() => {}} />,
    { locale: "id" },
  );

  expect(screen.getByLabelText("Judul")).toBeDefined();
  expect(screen.getByLabelText("Isi")).toBeDefined();
  expect(container.textContent).toContain("Pengaturan scene");
  expect(screen.queryByText("Heading")).toBeNull();
});
