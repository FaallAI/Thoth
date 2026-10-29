/// <reference types="bun-types" />

import { afterEach, expect, test } from "bun:test";
import { cleanup, fireEvent, screen } from "@testing-library/react";

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

test("says the timeline needs a wider screen and promises no unsupported detail", () => {
  const { state } = mount();
  expect(screen.getByText(/wider screen/i)).toBeDefined();
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
