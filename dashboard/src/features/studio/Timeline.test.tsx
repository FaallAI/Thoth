/// <reference types="bun-types" />

import { afterEach, expect, test } from "bun:test";
import { cleanup, fireEvent, screen, within } from "@testing-library/react";

import { render } from "@/test-render";

import { createEditorState, type EditorAction, type EditorState } from "./editor_state";
import { Timeline } from "./Timeline";
import { timelineDocument } from "./timeline-test-fixtures";

afterEach(cleanup);

/** Render the timeline over a state and collect everything it dispatches. */
function mount(overrides: Partial<EditorState> = {}) {
  const actions: EditorAction[] = [];
  const transport: string[] = [];
  const state = { ...createEditorState(timelineDocument()), ...overrides };
  render(
    <Timeline
      state={state}
      dispatch={(action) => actions.push(action)}
      onPlay={() => transport.push("play")}
      onPause={() => transport.push("pause")}
    />,
  );
  return { actions, state, transport };
}

/** Strip the generated ID so two payloads can be compared for equality. */
const payload = (action: EditorAction): Record<string, unknown> =>
  "operation" in action ? { ...action.operation, operation_id: "op" } : { ...action };

function drag(element: Element, from: number, to: number) {
  fireEvent.pointerDown(element, { clientX: from, button: 0 });
  fireEvent.pointerMove(window, { clientX: to });
  fireEvent.pointerUp(window, { clientX: to });
}

test("renders every track in order with its visibility, mute, and lock controls", () => {
  mount();
  const tracks = screen.getAllByRole("group", { name: /track/i });
  expect(tracks.map((track) => track.getAttribute("data-track-id"))).toEqual([
    "track_main",
    "track_broll",
    "track_music",
    "track_captions",
  ]);

  expect(screen.getByRole("button", { name: "Hide Music" })).toBeDefined();
  expect(screen.getByRole("button", { name: "Mute Music" })).toBeDefined();
  expect(screen.getByRole("button", { name: "Lock Music" })).toBeDefined();
  expect(screen.getByRole("button", { name: "Show Captions" })).toBeDefined();
  expect(screen.getByRole("button", { name: "Unlock Captions" })).toBeDefined();
});

test("a track header names its kind in the editor's own words", () => {
  mount();
  const music = screen.getByRole("group", { name: "Music track" });
  expect(music.textContent).toContain("music");
  expect(screen.getByRole("group", { name: "Main video track" }).textContent).toContain("main_video");
  expect(music.querySelector("svg.lucide-music")).not.toBeNull();
});

test("a clip shows what it is, not only where it sits", () => {
  mount();
  expect(screen.getByRole("button", { name: "Main video clip" }).textContent).toBe("Video");
  expect(screen.getByRole("button", { name: "Music clip" }).textContent).toBe("Audio");
});

test("marks the selected clip and reports selection changes", () => {
  const { actions } = mount({ selectedClipId: "clip_music" });
  const selected = screen.getByRole("button", { name: "Music clip" });
  expect(selected.getAttribute("aria-pressed")).toBe("true");

  fireEvent.click(screen.getByRole("button", { name: "Main video clip" }));
  expect(actions).toEqual([{ type: "select_clip", clipId: "clip_main" }]);
});

test("the ruler is the playhead: it reads as a timecode and never edits the document", () => {
  const { actions } = mount({ playheadFrame: 96 });
  const playhead = screen.getByRole("slider", { name: "Playhead" });
  expect(playhead.getAttribute("aria-valuemax")).toBe("299");
  expect(playhead.getAttribute("aria-valuenow")).toBe("96");
  expect(playhead.getAttribute("aria-valuetext")).toBe("0:03.2");
  expect(screen.getByText("0:05")).toBeDefined();

  fireEvent.keyDown(playhead, { key: "ArrowRight" });
  fireEvent.keyDown(playhead, { key: "ArrowLeft" });
  fireEvent.keyDown(playhead, { key: "ArrowRight", shiftKey: true });
  fireEvent.keyDown(playhead, { key: "Home" });
  fireEvent.keyDown(playhead, { key: "End" });
  expect(actions).toEqual([
    { type: "set_playhead", frame: 97 },
    { type: "set_playhead", frame: 95 },
    { type: "set_playhead", frame: 126 },
    { type: "set_playhead", frame: 0 },
    { type: "set_playhead", frame: 299 },
  ]);
});

test("pressing and dragging on the ruler seeks the preview", () => {
  const actions: EditorAction[] = [];
  const seeks: number[] = [];
  render(
    <Timeline
      state={{ ...createEditorState(timelineDocument()), zoom: 2 }}
      dispatch={(action) => actions.push(action)}
      onSeek={(frame) => seeks.push(frame)}
    />,
  );
  const ruler = screen.getByRole("slider", { name: "Playhead" });
  fireEvent.pointerDown(ruler, { clientX: 120, button: 0 });
  fireEvent.pointerMove(window, { clientX: 200 });
  fireEvent.pointerUp(window, { clientX: 200 });
  fireEvent.pointerMove(window, { clientX: 260 });
  expect(seeks).toEqual([60, 100]);
  expect(actions).toEqual([
    { type: "set_playhead", frame: 60 },
    { type: "set_playhead", frame: 100 },
  ]);
});

test("the transport reads the playhead and the length as timecodes", () => {
  mount({ playheadFrame: 96 });
  expect(screen.getByText("0:03.2 / 0:10.0")).toBeDefined();
});

test("one button plays and pauses the preview", () => {
  const { transport } = mount();
  fireEvent.click(screen.getByRole("button", { name: "Play" }));
  cleanup();
  const playing = mount({ playing: true });
  fireEvent.click(screen.getByRole("button", { name: "Pause" }));
  expect([...transport, ...playing.transport]).toEqual(["play", "pause"]);
});

test("zoom, snapping, and ripple are controls, not document edits", () => {
  const { actions } = mount();
  const snap = screen.getByRole("switch", { name: "Snap" });
  expect(snap.getAttribute("aria-checked")).toBe("true");
  fireEvent.click(screen.getByRole("button", { name: "Zoom in" }));
  fireEvent.click(screen.getByRole("button", { name: "Zoom out" }));
  fireEvent.click(snap);
  fireEvent.click(screen.getByRole("switch", { name: "Ripple" }));
  fireEvent.change(screen.getByRole("slider", { name: "Zoom" }), { target: { value: "1" } });
  expect(actions).toEqual([
    { type: "set_zoom", zoom: 2 },
    { type: "set_zoom", zoom: 0.5 },
    { type: "set_snapping", snapping: false },
    { type: "set_ripple", ripple: true },
    { type: "set_zoom", zoom: 2 },
  ]);
});

test("leaves the narrow-screen note to Studio and promises no unsupported detail", () => {
  const { state } = mount();
  expect(screen.queryByText(/wider screen/i)).toBeNull();
  expect(document.body.textContent).not.toMatch(/waveform|filmstrip/i);
  expect(state.draft).toEqual(timelineDocument());
});

test("dragging a clip previews while moving and commits exactly once", () => {
  const { actions } = mount();
  drag(screen.getByRole("button", { name: "Music clip" }), 150, 210);

  expect(actions.map((action) => action.type)).toEqual([
    "select_clip",
    "preview_timeline_operation",
    "commit_timeline_operation",
  ]);
  const move = {
    kind: "move_clip",
    operation_id: "op",
    clip_id: "clip_music",
    target_track_id: "track_music",
    from_frame: 210,
    ripple: false,
  };
  expect(payload(actions[1]!)).toEqual(move);
  expect(payload(actions[2]!)).toEqual(move);
});

test("a cancelled gesture restores the draft and queues nothing", () => {
  const { actions } = mount();
  const clip = screen.getByRole("button", { name: "Music clip" });
  fireEvent.pointerDown(clip, { clientX: 150, button: 0 });
  fireEvent.pointerMove(window, { clientX: 210 });
  fireEvent.keyDown(window, { key: "Escape" });
  fireEvent.pointerUp(window, { clientX: 210 });

  expect(actions.map((action) => action.type)).toEqual([
    "select_clip",
    "preview_timeline_operation",
    "cancel_timeline_preview",
  ]);
});

test("snapping pulls a moved clip onto a neighbouring edge and can be turned off", () => {
  const snapped = mount();
  drag(screen.getByRole("button", { name: "Music clip" }), 150, 125);
  expect(payload(snapped.actions[2]!)).toMatchObject({ from_frame: 120 });

  cleanup();
  const free = mount({ snapping: false });
  drag(screen.getByRole("button", { name: "Music clip" }), 150, 125);
  expect(payload(free.actions[2]!)).toMatchObject({ from_frame: 125 });
});

test("the trim handles emit trim operations bounded by their own clip", () => {
  const start = mount();
  drag(screen.getByRole("button", { name: "Trim start of Music clip" }), 150, 122);
  expect(payload(start.actions[1]!)).toEqual({
    kind: "trim_clip_start",
    operation_id: "op",
    clip_id: "clip_music",
    from_frame: 120,
  });

  cleanup();
  const end = mount();
  drag(screen.getByRole("button", { name: "Trim end of Music clip" }), 240, 295);
  expect(payload(end.actions[1]!)).toEqual({
    kind: "trim_clip_end",
    operation_id: "op",
    clip_id: "clip_music",
    end_frame: 300,
  });
});

test("labelled controls produce the same payload as the equivalent gesture", () => {
  const { actions } = mount({ selectedClipId: "clip_music", playheadFrame: 210 });
  fireEvent.click(screen.getByRole("button", { name: "Move clip to playhead" }));
  expect(payload(actions[0]!)).toEqual({
    kind: "move_clip",
    operation_id: "op",
    clip_id: "clip_music",
    target_track_id: "track_music",
    from_frame: 210,
    ripple: false,
  });

  fireEvent.click(screen.getByRole("button", { name: "Split clip at playhead" }));
  const split = payload(actions[1]!) as Record<string, unknown>;
  expect(split).toMatchObject({ kind: "split_clip", clip_id: "clip_music", split_frame: 210 });
  expect(split.left_clip_id).not.toBe(split.right_clip_id);
});

test("keyboard nudges move a clip by a single frame", () => {
  const { actions } = mount({ selectedClipId: "clip_music" });
  fireEvent.keyDown(screen.getByRole("button", { name: "Music clip" }), { key: "ArrowRight" });
  expect(payload(actions[0]!)).toEqual({
    kind: "move_clip",
    operation_id: "op",
    clip_id: "clip_music",
    target_track_id: "track_music",
    from_frame: 151,
    ripple: false,
  });
});

test("a locked clip explains itself and emits nothing", () => {
  const { actions } = mount({ selectedClipId: "clip_locked" });
  const clip = screen.getByRole("button", { name: "B-roll clip" });

  drag(clip, 150, 210);
  fireEvent.keyDown(clip, { key: "ArrowRight" });
  expect(actions.filter((action) => action.type !== "select_clip")).toEqual([]);
  expect(screen.getByText("Locked — unlock the clip to edit it")).toBeDefined();
  expect(
    screen.getByRole("button", { name: "Move clip to playhead" }).hasAttribute("disabled"),
  ).toBe(true);
});

test("a locked track keeps its own controls out of reach", () => {
  mount();
  expect(screen.getByRole("button", { name: "Show Captions" }).hasAttribute("disabled")).toBe(true);
  expect(screen.getByRole("button", { name: "Mute Captions" }).hasAttribute("disabled")).toBe(true);
  expect(screen.getByRole("button", { name: "Unlock Captions" }).hasAttribute("disabled")).toBe(
    false,
  );
});

test("track controls dispatch their own typed operations", () => {
  const { actions } = mount();
  fireEvent.click(screen.getByRole("button", { name: "Mute Music" }));
  expect(payload(actions[0]!)).toEqual({
    kind: "set_track_muted",
    operation_id: "op",
    track_id: "track_music",
    muted: true,
  });
});

test("lane names stay in sight while the lanes scroll, and take a quarter of a phone when view-only", () => {
  // e2e audit 2026-11-02, finding 7: at 430 they scrolled away, and their 192 px took half the screen.
  const header = () => within(screen.getByRole("group", { name: "Main video track" })).getByText("main_video").parentElement!;
  mount();
  expect(header().className).toContain("sticky");
  expect(header().className).toContain("w-48");
  expect(document.querySelector(".h-5.w-px")).not.toBeNull();
  cleanup();

  render(<Timeline state={createEditorState(timelineDocument())} dispatch={() => {}} onPlay={() => {}} onPause={() => {}} readOnly />);
  expect(header().className).toContain("sticky");
  expect(header().className).toContain("w-24");
  // e2e audit 2026-11-02: no separator is left over from the switches a view hides.
  expect(document.querySelector(".h-5.w-px")).toBeNull();
});

// Spec 2026-11-08 §5.1: the editing keys common editors share.
const key = (target: Element | Document | Window, key: string, init: KeyboardEventInit = {}) => fireEvent.keyDown(target, { key, ...init });
const ops = (actions: EditorAction[]) =>
  actions.flatMap((action) => (action.type === "commit_operations" ? action.operations.map((operation) => operation.kind) : []));

test("Delete removes the selected clip as one edit", () => {
  const { actions } = mount({ selectedClipId: "clip_main", selectedTrackId: "track_main" });
  key(document.body, "Delete");
  expect(ops(actions)).toEqual(["remove_clip"]);
});

test("S splits the selected clip at the playhead", () => {
  const { actions } = mount({ selectedClipId: "clip_main", selectedTrackId: "track_main", playheadFrame: 60 });
  key(document.body, "s");
  const split = actions.find((action) => action.type === "commit_operations");
  expect(split?.type === "commit_operations" && split.operations[0]).toMatchObject({ kind: "split_clip", split_frame: 60 });
});

test("keys typed in a field do nothing to the timeline", () => {
  const { actions, transport } = mount({ selectedClipId: "clip_main", selectedTrackId: "track_main", playheadFrame: 60 });
  const field = document.createElement("input");
  document.body.appendChild(field);
  try {
    for (const name of ["Delete", "s", " ", "Home"]) key(field, name);
  } finally {
    field.remove();
  }
  expect(actions).toEqual([]);
  expect(transport).toEqual([]);
});

test("Space on a focused button keeps the button's own meaning", () => {
  const { transport } = mount();
  key(screen.getByRole("button", { name: "Zoom in" }), " ");
  expect(transport).toEqual([]);
});

test("Space elsewhere plays", () => {
  const { transport } = mount();
  key(document.body, " ");
  expect(transport).toEqual(["play"]);
});

test("Home and End seek to the start and the last frame", () => {
  const { actions } = mount({ playheadFrame: 100 });
  key(document.body, "Home");
  key(document.body, "End");
  expect(actions.filter((action) => action.type === "set_playhead")).toEqual([
    { type: "set_playhead", frame: 0 },
    { type: "set_playhead", frame: 299 },
  ]);
});

test("Ctrl+0 fits the canvas into the lanes", () => {
  const { actions } = mount();
  Object.defineProperty(screen.getByTestId("timeline-lanes"), "clientWidth", { configurable: true, value: 1192 });
  key(document.body, "0", { ctrlKey: true });
  const zoom = actions.find((action) => action.type === "set_zoom");
  expect(zoom?.type === "set_zoom" && zoom.zoom).toBeCloseTo(1000 / 300, 3);
});

test("a locked clip ignores Delete and S", () => {
  const { actions } = mount({ selectedClipId: "clip_locked", selectedTrackId: "track_broll", playheadFrame: 170 });
  key(document.body, "Delete");
  key(document.body, "s");
  expect(actions).toEqual([]);
});

test("Escape clears the clip selection", () => {
  const { actions } = mount({ selectedClipId: "clip_main", selectedTrackId: "track_main" });
  key(document.body, "Escape");
  expect(actions).toEqual([{ type: "select_clip", clipId: "" }]);
});

test("a view-only timeline ignores editing keys", () => {
  const actions: EditorAction[] = [];
  render(
    <Timeline
      state={{ ...createEditorState(timelineDocument()), selectedClipId: "clip_main", selectedTrackId: "track_main" }}
      dispatch={(action) => actions.push(action)}
      readOnly
    />,
  );
  key(document.body, "Delete");
  expect(actions).toEqual([]);
});

// Spec 2026-11-08 §5.1, pointer: another lane, an empty lane, Ctrl+wheel, a track's name.
function withLaneUnderPointer(trackId: string, run: () => void) {
  const original = document.elementsFromPoint;
  const lane = document.querySelector(`[data-track-id="${trackId}"]`)!;
  document.elementsFromPoint = () => [lane];
  try {
    run();
  } finally {
    document.elementsFromPoint = original;
  }
}

const lastMove = (actions: EditorAction[]) =>
  actions.filter((action) => action.type === "commit_timeline_operation").at(-1);

test("a clip dragged onto another compatible lane moves there", () => {
  const { actions } = mount();
  const clip = screen.getByRole("button", { name: "Main video clip" });
  withLaneUnderPointer("track_broll", () => {
    fireEvent.pointerDown(clip, { clientX: 10, clientY: 10, button: 0 });
    fireEvent.pointerMove(window, { clientX: 10, clientY: 60 });
    fireEvent.pointerUp(window, { clientX: 10, clientY: 60 });
  });
  expect(lastMove(actions)).toMatchObject({ operation: { kind: "move_clip", target_track_id: "track_broll", from_frame: 0 } });
});

test("a clip dragged over an incompatible lane stays on its track", () => {
  const { actions } = mount();
  const clip = screen.getByRole("button", { name: "Main video clip" });
  withLaneUnderPointer("track_music", () => {
    fireEvent.pointerDown(clip, { clientX: 10, clientY: 10, button: 0 });
    fireEvent.pointerMove(window, { clientX: 10, clientY: 100 });
    fireEvent.pointerUp(window, { clientX: 10, clientY: 100 });
  });
  expect(lastMove(actions)).toMatchObject({ operation: { kind: "move_clip", target_track_id: "track_main" } });
});

test("a click on an empty part of a lane seeks there", () => {
  const { actions } = mount({ zoom: 4 });
  const well = document.querySelector('[data-track-id="track_music"] [data-lane-well]')!;
  fireEvent.pointerDown(well, { clientX: 200, button: 0 });
  expect(actions).toContainEqual({ type: "set_playhead", frame: 50 });
});

test("a click on a clip does not seek", () => {
  const { actions } = mount({ zoom: 4 });
  fireEvent.pointerDown(screen.getByRole("button", { name: "Music clip" }), { clientX: 700, button: 0 });
  expect(actions.some((action) => action.type === "set_playhead")).toBe(false);
});

test("Ctrl+wheel zooms the lanes and a plain wheel does not", () => {
  const { actions } = mount({ zoom: 2 });
  const lanes = screen.getByTestId("timeline-lanes");
  // The test DOM's WheelEvent drops `ctrlKey`, so it is set on the event itself.
  const wheel = (ctrlKey: boolean) => {
    const event = new WheelEvent("wheel", { deltaY: 240, bubbles: true, cancelable: true });
    Object.defineProperty(event, "ctrlKey", { value: ctrlKey });
    lanes.dispatchEvent(event);
  };
  wheel(false);
  expect(actions.some((action) => action.type === "set_zoom")).toBe(false);
  wheel(true);
  const zoom = actions.find((action) => action.type === "set_zoom");
  expect(zoom?.type === "set_zoom" && zoom.zoom).toBeLessThan(2);
});

test("a click on a track's name selects the track", () => {
  const { actions } = mount();
  fireEvent.click(screen.getByRole("button", { name: "Select Music track" }));
  expect(actions).toContainEqual({ type: "select_track", trackId: "track_music" });
});
