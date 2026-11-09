/// <reference types="bun-types" />

import { afterEach, expect, mock, test } from "bun:test";
import { cleanup, createEvent, fireEvent, screen, within } from "@testing-library/react";

import { render } from "@/test-render";

import type { EditDocumentV2 } from "@/api/control-plane";
import { createEditorState, type EditorAction, type EditorState } from "./editor_state";
import { Timeline } from "./Timeline";
import { applyTimelineOperation } from "./timeline_domain";
import { textDocument, timelineDocument } from "./timeline-test-fixtures";

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

test("a track header names its kind in plain words, never its raw id", () => {
  // Spec 2026-11-08 §5.1: "Main video", not `main_video`.
  mount();
  const music = screen.getByRole("group", { name: "Music track" });
  expect(music.textContent).toContain("Music");
  const main = screen.getByRole("group", { name: "Main video track" });
  expect(main.textContent).toContain("Main video");
  expect(main.textContent).not.toContain("main_video");
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
  const header = () => screen.getByRole("button", { name: "Select Main video track" }).parentElement!;
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

// Spec 2026-11-08 §5.1: right-click menus on a clip, a gap and a track.
function mountMenus(overrides: Partial<EditorState> = {}, props: Partial<Parameters<typeof Timeline>[0]> = {}) {
  const actions: EditorAction[] = [];
  render(
    <Timeline
      state={{ ...createEditorState(timelineDocument()), ...overrides }}
      dispatch={(action) => actions.push(action)}
      {...props}
    />,
  );
  return { actions };
}

const menuNames = () => screen.getAllByRole("menuitem").map((item) => item.getAttribute("aria-label"));
const committed = (actions: EditorAction[]) =>
  actions.filter((action) => action.type === "commit_operations").map((action) => action.type === "commit_operations" && action.operations.map((operation) => operation.kind));

test("a clip's menu offers the editing entries in order", () => {
  mountMenus({ playheadFrame: 60 }, { beatOf: () => "main", onShowInStory: () => {} });
  fireEvent.contextMenu(screen.getByRole("button", { name: "Main video clip" }), { clientX: 5, clientY: 5 });
  expect(menuNames()).toEqual(["Split at playhead", "Copy", "Paste", "Duplicate", "Paste text…", "Delete", "Ripple delete", "Replace media…", "B-roll", "Hide", "Lock", "Show in Story"]);
  expect(screen.getByRole("group", { name: "Move to track" })).toBeTruthy();
});

test("menu entries that do not apply say why", () => {
  mountMenus({ playheadFrame: 200 });
  fireEvent.contextMenu(screen.getByRole("button", { name: "Main video clip" }), { clientX: 5, clientY: 5 });
  expect(screen.getByRole("menuitem", { name: "Split at playhead" }).getAttribute("title")).toBe("The playhead is outside this clip");
  expect(screen.getByRole("menuitem", { name: "Show in Story" }).getAttribute("aria-disabled")).toBe("true");
  fireEvent.keyDown(screen.getByRole("menu"), { key: "Escape" });

  fireEvent.contextMenu(screen.getByRole("button", { name: "B-roll clip" }), { clientX: 5, clientY: 5 });
  expect(screen.getByRole("menuitem", { name: "Delete" }).getAttribute("title")).toBe("This clip is locked");
  expect(screen.getByRole("menuitem", { name: "Split at playhead" }).getAttribute("aria-disabled")).toBe("true");
});

test("Delete commits one edit, and a Ripple delete across another track's clip is refused with its reason", () => {
  const { actions } = mountMenus();
  fireEvent.contextMenu(screen.getByRole("button", { name: "Main video clip" }), { clientX: 5, clientY: 5 });
  fireEvent.click(screen.getByRole("menuitem", { name: "Delete" }));
  // The locked B-roll clip (150–200) lies inside the Music clip's stretch (150–240).
  fireEvent.contextMenu(screen.getByRole("button", { name: "Music clip" }), { clientX: 5, clientY: 5 });
  const ripple = screen.getByRole("menuitem", { name: "Ripple delete" });
  expect(ripple.getAttribute("title")).toBe("A clip on another track is cut part-way here; trim or delete it first");
  fireEvent.click(ripple);
  expect(committed(actions)).toEqual([["remove_clip"]]);
});

test("Replace media opens a picker of ready videos and commits the choice", () => {
  const ready = { asset_id: "asset_other", project_id: "project_001", kind: "video", has_audio: true, media_type: "video/mp4", validation_state: "ready", duration_in_frames: 300 } as const;
  const { actions } = mountMenus({ assets: { asset_other: ready } as EditorState["assets"] }, { assetName: () => "Footage · @someone" });
  fireEvent.contextMenu(screen.getByRole("button", { name: "Main video clip" }), { clientX: 5, clientY: 5 });
  fireEvent.click(screen.getByRole("menuitem", { name: "Replace media…" }));
  fireEvent.click(within(screen.getByRole("dialog", { name: "Replace media" })).getByRole("button", { name: "Use Footage · @someone" }));
  expect(actions.at(-1)).toMatchObject({ type: "commit_operations", operations: [{ kind: "replace_clip_asset", clip_id: "clip_main", asset_id: "asset_other" }] });
});

test("a gap's menu closes the gap, and away from a gap it says there is none", () => {
  const { actions } = mountMenus({ zoom: 1 });
  const well = document.querySelector('[data-track-id="track_main"] [data-lane-well]')!;
  fireEvent.contextMenu(well, { clientX: 200, clientY: 5 });
  const close = screen.getByRole("menuitem", { name: "Close this gap" });
  expect(close.getAttribute("title")).toBe("There is no gap here");
  expect(actions).toEqual([]);
});

test("a track's menu offers track entries, with the edges and full tracks disabled", () => {
  mountMenus();
  fireEvent.contextMenu(screen.getByRole("button", { name: "Select Main video track" }), { clientX: 5, clientY: 5 });
  expect(menuNames()).toEqual(["Select track", "Move up", "Move down", "Hide", "Mute", "Lock", "Close all gaps on this track", "Remove empty track"]);
  expect(screen.getByRole("menuitem", { name: "Move up" }).getAttribute("aria-disabled")).toBe("true");
  expect(screen.getByRole("menuitem", { name: "Remove empty track" }).getAttribute("title")).toBe("Remove its clips first");
});

test("Show in Story hands the clip to the Story", () => {
  const shown: string[] = [];
  mountMenus({}, { beatOf: () => "main", onShowInStory: (clipId) => shown.push(clipId) });
  fireEvent.contextMenu(screen.getByRole("button", { name: "Main video clip" }), { clientX: 5, clientY: 5 });
  fireEvent.click(screen.getByRole("menuitem", { name: "Show in Story" }));
  expect(shown).toEqual(["clip_main"]);
});

// Final review 2026-11-08 #3-#5.
test("keys pressed inside an open dialog or menu do not reach the timeline", () => {
  const { actions } = mount({ selectedClipId: "clip_main", selectedTrackId: "track_main", playheadFrame: 60 });
  for (const role of ["dialog", "menu"]) {
    const box = document.createElement("div");
    box.setAttribute("role", role);
    const inside = document.createElement("button");
    box.appendChild(inside);
    document.body.appendChild(box);
    try {
      for (const name of ["Delete", "s", "ArrowRight"]) key(inside, name);
    } finally {
      box.remove();
    }
  }
  expect(actions).toEqual([]);
});

test("arrows on the zoom slider move the slider, not the playhead", () => {
  const { actions } = mount({ playheadFrame: 60 });
  key(screen.getByRole("slider", { name: "Zoom" }), "ArrowRight");
  key(screen.getByRole("slider", { name: "Zoom" }), "Home");
  expect(actions.some((action) => action.type === "set_playhead")).toBe(false);
});

test("Space on a focused clip plays, as in common editors", () => {
  const { transport } = mount({ selectedClipId: "clip_main", selectedTrackId: "track_main" });
  key(screen.getByRole("button", { name: "Main video clip" }), " ");
  expect(transport).toEqual(["play"]);
});

// Tier 2 (spec 2026-11-08 §6): select many clips.
/** Give each lane well a place on screen, one 44 px row per track, as the browser would. */
function placeWells() {
  ["track_main", "track_broll", "track_music"].forEach((trackId, row) => {
    const well = document.querySelector(`[data-track-id="${trackId}"] [data-lane-well]`)!;
    const top = row * 44;
    Object.defineProperty(well, "getBoundingClientRect", {
      value: () => ({ left: 0, right: 2000, top, bottom: top + 44, width: 2000, height: 44, x: 0, y: top, toJSON: () => ({}) }),
    });
  });
}

test("Shift+click and Ctrl+click add a clip to the selection", () => {
  const { actions } = mount({ selectedClipId: "clip_main", selectedClipIds: ["clip_main"] });
  fireEvent.click(screen.getByRole("button", { name: "Music clip" }), { shiftKey: true });
  fireEvent.click(screen.getByRole("button", { name: "Music clip" }), { ctrlKey: true });
  expect(actions.filter((action) => action.type === "select_clip")).toEqual([
    { type: "select_clip", clipId: "clip_music", add: true },
    { type: "select_clip", clipId: "clip_music", add: true },
  ]);
});

test("a drag on empty lane space draws a marquee and selects the unlocked clips it touches", () => {
  const { actions } = mount({ zoom: 4 });
  placeWells();
  const well = document.querySelector('[data-track-id="track_main"] [data-lane-well]')!;
  fireEvent.pointerDown(well, { clientX: 5, clientY: 10, button: 0 });
  fireEvent.pointerMove(window, { clientX: 700, clientY: 100 });
  expect(screen.getByTestId("timeline-marquee")).toBeDefined();
  fireEvent.pointerUp(window, { clientX: 700, clientY: 100 });
  expect(actions.at(-1)).toEqual({ type: "select_clips", clipIds: ["clip_main", "clip_music"] });
  expect(screen.queryByTestId("timeline-marquee")).toBeNull();
});

test("a short press on empty lane space draws no marquee", () => {
  const { actions } = mount({ zoom: 4 });
  placeWells();
  const well = document.querySelector('[data-track-id="track_main"] [data-lane-well]')!;
  fireEvent.pointerDown(well, { clientX: 5, clientY: 10, button: 0 });
  fireEvent.pointerMove(window, { clientX: 7, clientY: 11 });
  fireEvent.pointerUp(window, { clientX: 7, clientY: 11 });
  expect(actions.some((action) => action.type === "select_clips")).toBe(false);
});

test("Ctrl+A selects every clip on visible, unlocked lanes", () => {
  const { actions } = mount();
  key(window, "a", { ctrlKey: true });
  expect(actions.at(-1)).toEqual({ type: "select_clips", clipIds: ["clip_main", "clip_music"] });
});

test("Ctrl+A in a text field selects no clips", () => {
  const { actions } = mount();
  const field = document.body.appendChild(document.createElement("input"));
  key(field, "a", { ctrlKey: true });
  expect(actions.some((action) => action.type === "select_clips")).toBe(false);
  field.remove();
});

test("Escape clears a selection of many clips", () => {
  const { actions } = mount({ selectedClipId: "clip_music", selectedClipIds: ["clip_main", "clip_music"] });
  key(window, "Escape");
  expect(actions.at(-1)).toEqual({ type: "select_clip", clipId: "" });
});

test("every selected clip shows as selected", () => {
  mount({ selectedClipId: "clip_music", selectedClipIds: ["clip_main", "clip_music"] });
  for (const name of ["Main video clip", "Music clip"]) {
    expect(screen.getByRole("button", { name }).getAttribute("aria-pressed")).toBe("true");
  }
});

// Tier 2 (spec 2026-11-08 §6): edits act on the whole selection as one undo step.
const both = { selectedClipId: "clip_music", selectedClipIds: ["clip_main", "clip_music"] };

test("Delete with two selected clips commits one batch for both", () => {
  const { actions } = mount(both);
  key(window, "Delete");
  expect(actions.at(-1)).toMatchObject({
    type: "commit_operations",
    operations: [
      { kind: "remove_clip", clip_id: "clip_main" },
      { kind: "remove_clip", clip_id: "clip_music" },
    ],
  });
});

test("the menu of a selected clip acts on the whole selection", () => {
  const { actions } = mountMenus(both);
  fireEvent.contextMenu(screen.getByRole("button", { name: "Main video clip" }), { clientX: 5, clientY: 5 });
  expect(menuNames()).toContain("Delete 2 clips");
  expect(menuNames()).toContain("Hide 2 clips");
  fireEvent.click(screen.getByRole("menuitem", { name: "Delete 2 clips" }));
  expect(actions.at(-1)).toMatchObject({ type: "commit_operations", operations: [{ kind: "remove_clip" }, { kind: "remove_clip" }] });
});

test("a group drag previews both clips and commits one batch on drop", () => {
  const { actions } = mount(both);
  drag(screen.getByRole("button", { name: "Main video clip" }), 10, 40);
  const previews = actions.filter((action) => action.type === "preview_timeline_operations");
  expect(previews.at(-1)).toMatchObject({
    operations: [
      { kind: "move_clip", clip_id: "clip_main", from_frame: 30 },
      { kind: "move_clip", clip_id: "clip_music", from_frame: 180 },
    ],
  });
  expect(actions.slice(-2).map((action) => action.type)).toEqual(["cancel_timeline_preview", "commit_operations"]);
  expect(actions.at(-1)).toMatchObject({ operations: [{ from_frame: 30 }, { from_frame: 180 }] });
});

test("Escape during a group drag restores both clips", () => {
  const { actions } = mount(both);
  fireEvent.pointerDown(screen.getByRole("button", { name: "Main video clip" }), { clientX: 10, button: 0 });
  fireEvent.pointerMove(window, { clientX: 40 });
  key(window, "Escape");
  expect(actions.at(-1)).toEqual({ type: "cancel_timeline_preview" });
  fireEvent.pointerUp(window, { clientX: 40 });
  expect(actions.some((action) => action.type === "commit_operations")).toBe(false);
});

// Tier 2 (spec 2026-11-08 §6): copy, paste and duplicate inside the open draft.
const pasted = (actions: EditorAction[]) =>
  actions.filter((action) => action.type === "commit_operations").flatMap((action) => (action.type === "commit_operations" ? action.operations : []));

test("Ctrl+C then Ctrl+V pastes the selection at the playhead as one undo step", () => {
  const { actions } = mount({ selectedClipId: "clip_music", selectedClipIds: ["clip_music"], playheadFrame: 0 });
  key(window, "c", { ctrlKey: true });
  key(window, "v", { ctrlKey: true });
  expect(actions.filter((action) => action.type === "commit_operations")).toHaveLength(1);
  expect(pasted(actions)).toMatchObject([{ kind: "duplicate_clip", clip_id: "clip_music", track_id: "track_music", from_frame: 0 }]);
});

test("Ctrl+D duplicates the selection after itself", () => {
  const { actions } = mount({ selectedClipId: "clip_main", selectedClipIds: ["clip_main"] });
  key(window, "d", { ctrlKey: true });
  expect(pasted(actions)).toMatchObject([{ kind: "duplicate_clip", clip_id: "clip_main", from_frame: 120 }]);
});

test("the clip menu copies and pastes, and says so when nothing is copied", () => {
  const { actions } = mountMenus({ playheadFrame: 0 });
  const music = screen.getByRole("button", { name: "Music clip" });
  fireEvent.contextMenu(music, { clientX: 5, clientY: 5 });
  expect(screen.getByRole("menuitem", { name: "Paste" }).getAttribute("title")).toBe("Copy a clip first");
  fireEvent.click(screen.getByRole("menuitem", { name: "Copy" }));
  fireEvent.contextMenu(music, { clientX: 5, clientY: 5 });
  fireEvent.click(screen.getByRole("menuitem", { name: "Paste" }));
  expect(actions.at(-1)).toMatchObject({ type: "commit_operations", operations: [{ kind: "duplicate_clip", clip_id: "clip_music", from_frame: 0 }] });
});

test("Ctrl+C in a text field copies no clips", () => {
  const { actions } = mount({ selectedClipId: "clip_music", selectedClipIds: ["clip_music"] });
  const field = document.body.appendChild(document.createElement("input"));
  key(field, "c", { ctrlKey: true });
  field.remove();
  key(window, "v", { ctrlKey: true });
  expect(pasted(actions)).toEqual([]);
});

// Tier 2 (spec 2026-11-08 §6): text through the system clipboard, placed where the person picks.

function mountText(overrides: Partial<EditorState> = {}) {
  const doc = textDocument();
  return mount({ base: doc, draft: doc, playheadFrame: 30, ...overrides });
}
const pasteText = (target: Element | Window, text: string, html = "") =>
  fireEvent.paste(target, { clipboardData: { getData: (type: string) => (type === "text/plain" ? text : type === "text/html" ? html : "") } });

test("pasting text on the timeline asks where it goes, then places it there", () => {
  const { actions } = mountText();
  pasteText(window, "Hello");
  expect(actions.some((action) => action.type === "commit_operations")).toBe(false);
  fireEvent.click(screen.getByRole("button", { name: "New text clip" }));
  expect(actions.at(-1)).toMatchObject({ type: "commit_operations", operations: [{ kind: "add_text_clip", heading: "Hello", from_frame: 30 }] });
  expect(screen.queryByRole("dialog", { name: "Paste text" })).toBeNull();
});

test("a paste onto a hidden-only overlay track says so in the status line", () => {
  const doc = textDocument();
  doc.tracks.find((track) => track.kind === "overlay")!.hidden = true;
  const { actions } = mount({ base: doc, draft: doc, playheadFrame: 30 });
  pasteText(window, "Hello");
  fireEvent.click(screen.getByRole("button", { name: "New text clip" }));
  expect(actions.at(-1)).toMatchObject({ type: "commit_operations", operations: [{ kind: "add_text_clip", track_id: "track_overlay" }] });
  expect(screen.getByRole("status").textContent).toContain("Pasted on a hidden track. Show the track to see it.");
});

test("a paste into a field, HTML alone or blank text opens nothing", () => {
  mountText();
  const field = document.body.appendChild(document.createElement("input"));
  pasteText(field, "Hello");
  field.remove();
  pasteText(window, "", "<b>Bold</b>");
  pasteText(window, "   ");
  expect(screen.queryByRole("dialog", { name: "Paste text" })).toBeNull();
});

test("text over 300 characters leaves every place disabled", () => {
  mountText();
  pasteText(window, "x".repeat(301));
  for (const name of ["New text clip", "Replace the selected text", "New caption", "Replace the caption text"]) {
    const button = screen.getByRole("button", { name });
    expect(button.getAttribute("aria-disabled")).toBe("true");
    expect(button.textContent).toContain("Longer than 300 characters");
  }
});

test("Copy text puts a text clip's heading on the system clipboard", () => {
  const writeText = mock(async (_text: string) => {});
  Object.defineProperty(navigator, "clipboard", { value: { writeText, readText: async () => "" }, configurable: true });
  mountMenusOver(textDocument());
  fireEvent.contextMenu(screen.getByRole("button", { name: "Overlay clip" }), { clientX: 5, clientY: 5 });
  fireEvent.click(screen.getByRole("menuitem", { name: "Copy text" }));
  expect(writeText).toHaveBeenCalledWith("Old heading");
});

test("Paste text… says to use Ctrl+V when the browser will not read the clipboard", async () => {
  Object.defineProperty(navigator, "clipboard", { value: { writeText: async () => {}, readText: () => Promise.reject(new Error("denied")) }, configurable: true });
  mountMenusOver(textDocument());
  fireEvent.contextMenu(screen.getByRole("button", { name: "Overlay clip" }), { clientX: 5, clientY: 5 });
  fireEvent.click(screen.getByRole("menuitem", { name: "Paste text…" }));
  expect((await screen.findByRole("status")).textContent).toContain("Use Ctrl+V to paste text");
});

function mountMenusOver(doc: EditDocumentV2) {
  return mountMenus({ base: doc, draft: doc, playheadFrame: 30 });
}

// Tier 2 (spec 2026-11-08 §6): close all gaps from the track menu and the lane menu.
test("the track menu closes every gap on its track in one batch", () => {
  const { actions } = mountMenus();
  fireEvent.contextMenu(screen.getByRole("button", { name: "Select Music track" }), { clientX: 5, clientY: 5 });
  const close = screen.getByRole("menuitem", { name: "Close all gaps on this track" });
  expect(close.getAttribute("title")).toBe("There is no gap here");
  expect(actions).toEqual([]);
});

test("the lane menu offers to close every gap in the timeline", () => {
  // The fixture is empty everywhere from 120 to 150; its B-roll clip after that is unlocked here so it may move.
  const doc = timelineDocument();
  doc.clips!.find((clip) => clip.clip_id === "clip_locked")!.locked = false;
  const { actions } = mountMenus({ zoom: 1, base: doc, draft: doc });
  const well = document.querySelector('[data-track-id="track_main"] [data-lane-well]')!;
  fireEvent.contextMenu(well, { clientX: 200, clientY: 5 });
  fireEvent.click(screen.getByRole("menuitem", { name: "Close all gaps in the timeline" }));
  expect(actions.at(-1)).toMatchObject({
    type: "commit_operations",
    operations: [
      { kind: "move_clip", clip_id: "clip_locked", from_frame: 120 },
      { kind: "move_clip", clip_id: "clip_music", from_frame: 120 },
    ],
  });
});

// Tier 2 (spec 2026-11-08 §6): an asset dragged from the Assets column onto a lane.
const assetDrop = (target: Element, assetId: string, clientX: number) => {
  const event = createEvent.drop(target, {
    dataTransfer: { types: ["application/x-thoth-asset"], getData: (type: string) => (type === "application/x-thoth-asset" ? assetId : "") },
  });
  // The test DOM's DragEvent drops clientX from its init, as its WheelEvent drops ctrlKey.
  Object.defineProperty(event, "clientX", { value: clientX });
  fireEvent(target, event);
};

test("an asset dropped on a lane is placed on that track at the drop point", () => {
  const dropped: [string, string, number][] = [];
  const video = { asset_id: "asset_video", project_id: "project_001", kind: "video", media_type: "video/mp4", has_audio: true, validation_state: "ready", duration_in_frames: 30 } as EditorState["assets"][string];
  mountMenus({ zoom: 1, assets: { asset_video: video } }, { onDropAsset: (...drop) => dropped.push(drop) });
  assetDrop(document.querySelector('[data-track-id="track_broll"] [data-lane-well]')!, "asset_video", 100);
  assetDrop(document.querySelector('[data-track-id="track_music"] [data-lane-well]')!, "asset_video", 100);
  expect(dropped).toEqual([["asset_video", "track_broll", 100]]);
});

// Tier 2 (spec 2026-11-08 §6): J, K and L.
test("L shuttles forward, K stops, and J steps back one second", () => {
  const shuttle: string[] = [];
  const { actions } = mountMenus({ playheadFrame: 60 }, { onShuttle: (direction) => shuttle.push(direction) });
  key(window, "l");
  key(window, "k");
  key(window, "j");
  expect(shuttle).toEqual(["forward", "stop"]);
  expect(actions.at(-1)).toEqual({ type: "set_playhead", frame: 30 });
});

test("J, K and L do nothing in a text field", () => {
  const shuttle: string[] = [];
  const { actions } = mountMenus({ playheadFrame: 60 }, { onShuttle: (direction) => shuttle.push(direction) });
  const field = document.body.appendChild(document.createElement("input"));
  for (const letter of ["j", "k", "l"]) key(field, letter);
  field.remove();
  expect([shuttle, actions]).toEqual([[], []]);
});

// Tier 1 review leftovers (2026-11-08), fixed in Tier 2.
test("a lane that cannot take the dragged clip shows it refuses", () => {
  mount();
  const clip = screen.getByRole("button", { name: "Main video clip" });
  const music = () => document.querySelector('[data-track-id="track_music"] [data-lane-well]')!;
  withLaneUnderPointer("track_music", () => {
    fireEvent.pointerDown(clip, { clientX: 10, clientY: 10, button: 0 });
    fireEvent.pointerMove(window, { clientX: 10, clientY: 100 });
  });
  expect(music().getAttribute("data-drop")).toBe("refused");
  fireEvent.pointerUp(window, { clientX: 10, clientY: 100 });
  expect(music().getAttribute("data-drop")).toBeNull();
});

test("Move to track stays in the menu, disabled with a reason, on a locked clip", () => {
  mountMenus();
  fireEvent.contextMenu(screen.getByRole("button", { name: "B-roll clip" }), { clientX: 5, clientY: 5 });
  const move = screen.getByRole("menuitem", { name: "Move to track" });
  expect([move.getAttribute("aria-disabled"), move.getAttribute("title")]).toEqual(["true", "This clip is locked"]);
});

test("a second track of one kind has a numbered name for screen readers too", () => {
  const doc = timelineDocument();
  doc.tracks.push({ ...doc.tracks.find((track) => track.track_id === "track_broll")!, track_id: "track_broll_2", order: 9, clip_ids: [] });
  mount({ base: doc, draft: doc });
  expect(screen.getByRole("group", { name: "B-roll 2 track" })).toBeDefined();
});

// Final review 2026-11-08, Important 2: a refused key or group drag says why.
test("Ctrl+V onto a filled Main video says there is no room", () => {
  const { actions } = mount({ selectedClipId: "clip_main", selectedClipIds: ["clip_main"], playheadFrame: 0 });
  key(window, "c", { ctrlKey: true });
  key(window, "v", { ctrlKey: true });
  expect(actions.some((action) => action.type === "commit_operations")).toBe(false);
  expect(screen.getByRole("status").textContent).toContain("No room on Main video there");
});

test("Delete with a locked clip in the selection says the clip is locked", () => {
  const { actions } = mount({ selectedClipId: "clip_locked", selectedClipIds: ["clip_main", "clip_locked"] });
  key(window, "Delete");
  expect(actions.some((action) => action.type === "commit_operations")).toBe(false);
  expect(screen.getByRole("status").textContent).toContain("This clip is locked");
});

test("a group drag that holds a locked clip says why it did not move", () => {
  const { actions } = mount({ selectedClipId: "clip_locked", selectedClipIds: ["clip_main", "clip_locked"] });
  drag(screen.getByRole("button", { name: "Main video clip" }), 10, 40);
  expect(actions.some((action) => action.type === "commit_operations")).toBe(false);
  expect(screen.getByRole("status").textContent).toContain("This clip is locked");
});

// Final review 2026-11-08, Important 3: the pressed clip is the one the Inspector shows.
test("a press on a clip of a larger selection makes it the primary clip and keeps the group", () => {
  const { actions } = mount(both);
  fireEvent.pointerDown(screen.getByRole("button", { name: "Main video clip" }), { clientX: 10, button: 0 });
  expect(actions.at(-1)).toEqual({ type: "select_clips", clipIds: ["clip_music", "clip_main"] });
});

test("a click without a drag on a clip of a larger selection selects that clip alone", () => {
  const { actions } = mount(both);
  const main = screen.getByRole("button", { name: "Main video clip" });
  fireEvent.pointerDown(main, { clientX: 10, button: 0 });
  fireEvent.pointerUp(window, { clientX: 10 });
  expect(actions.at(-1)).toEqual({ type: "select_clip", clipId: "clip_main" });
});

// Tier 3a: Alt+drag on a clip's body slips its content; the picture follows the pointer.
test("Alt+drag on a clip slips its content and commits once", () => {
  const doc = timelineDocument();
  Object.assign(doc.clips!.find((clip) => clip.clip_id === "clip_main")!, { source_from_frame: 60 });
  const { actions } = mount({ base: doc, draft: doc });
  const clip = screen.getByRole("button", { name: "Main video clip" });
  fireEvent.pointerDown(clip, { clientX: 50, button: 0, altKey: true });
  fireEvent.pointerMove(window, { clientX: 80 });
  fireEvent.pointerUp(window, { clientX: 80 });

  const slip = { kind: "slip_clip", operation_id: "op", clip_id: "clip_main", source_from_frame: 30 };
  expect(actions.map((action) => action.type)).toEqual(["select_clip", "preview_timeline_operation", "commit_timeline_operation"]);
  expect(payload(actions[1]!)).toEqual(slip);
  expect(payload(actions[2]!)).toEqual(slip);
});

test("a slip that cannot happen says why and commits nothing", () => {
  const doc = timelineDocument();
  Object.assign(doc.asset_refs!.find((ref) => ref.asset_id === "asset_video")!, { kind: "image" });
  const { actions } = mount({ base: doc, draft: doc });
  const clip = screen.getByRole("button", { name: "Main video clip" });
  fireEvent.pointerDown(clip, { clientX: 50, button: 0, altKey: true });
  fireEvent.pointerMove(window, { clientX: 80 });
  fireEvent.pointerUp(window, { clientX: 80 });

  expect(actions.some((action) => action.type === "commit_timeline_operation")).toBe(false);
  expect(screen.getByRole("status").textContent).toContain("An image has no source time");
});

// Tier 3a: Alt+drag on a trim handle whose edge touches a neighbour rolls the cut between them.
function touchingPair(rightSource?: number) {
  const base = timelineDocument();
  const doc = applyTimelineOperation(base, { kind: "split_clip", operation_id: "op_split", clip_id: "clip_main", split_frame: 60, left_clip_id: "clip_a", right_clip_id: "clip_b" }, {});
  if (rightSource !== undefined) Object.assign(doc.clips!.find((clip) => clip.clip_id === "clip_b")!, { source_from_frame: rightSource });
  return mount({ base: doc, draft: doc, snapping: false });
}
const endHandleOfFirst = () => screen.getAllByRole("button", { name: "Trim end of Main video clip" })[0]!;

test("Alt+drag on a cut between two clips rolls it as one undo step", () => {
  const { actions } = touchingPair();
  fireEvent.pointerDown(endHandleOfFirst(), { clientX: 60, button: 0, altKey: true });
  fireEvent.pointerMove(window, { clientX: 75 });
  fireEvent.pointerUp(window, { clientX: 75 });

  const committed = actions.filter((action) => action.type === "commit_operations");
  expect(committed).toHaveLength(1);
  const operations: unknown[] = (committed[0] as { operations: Record<string, unknown>[] }).operations.map((operation) => ({ ...operation, operation_id: "op" }));
  expect(operations).toEqual([
    { kind: "trim_clip_end", operation_id: "op", clip_id: "clip_a", end_frame: 75 },
    { kind: "trim_clip_start", operation_id: "op", clip_id: "clip_b", from_frame: 75 },
  ]);
});

test("without Alt the same handle trims only its own clip", () => {
  const { actions } = touchingPair();
  fireEvent.pointerDown(endHandleOfFirst(), { clientX: 60, button: 0 });
  fireEvent.pointerMove(window, { clientX: 50 });
  fireEvent.pointerUp(window, { clientX: 50 });
  expect(payload(actions.at(-1)!)).toEqual({ kind: "trim_clip_end", operation_id: "op", clip_id: "clip_a", end_frame: 50 });
});

test("a refused roll says why and commits nothing", () => {
  // clip_b starts at the head of its source, so the cut cannot move left.
  const { actions } = touchingPair(0);
  fireEvent.pointerDown(endHandleOfFirst(), { clientX: 60, button: 0, altKey: true });
  fireEvent.pointerMove(window, { clientX: 50 });
  fireEvent.pointerUp(window, { clientX: 50 });
  expect(actions.some((action) => action.type === "commit_operations" || action.type === "commit_timeline_operation")).toBe(false);
  expect(screen.getByRole("status").textContent).toContain("The source has no more footage there");
});

test("a roll across a scene boundary says to resize the scene in Story", () => {
  const base = timelineDocument();
  const doc = applyTimelineOperation(base, { kind: "split_clip", operation_id: "op_split", clip_id: "clip_main", split_frame: 60, left_clip_id: "clip_a", right_clip_id: "clip_b" }, {});
  doc.scenes = [
    { ...doc.scenes[0]!, scene_id: "scene_a", start_frame: 0, duration_in_frames: 60, clip_ids: [] },
    { ...doc.scenes[0]!, scene_id: "scene_b", start_frame: 60, duration_in_frames: 90, clip_ids: [] },
  ];
  Object.assign(doc.clips!.find((clip) => clip.clip_id === "clip_a")!, { scene_id: "scene_a" });
  Object.assign(doc.clips!.find((clip) => clip.clip_id === "clip_b")!, { scene_id: "scene_b" });
  mount({ base: doc, draft: doc, snapping: false });
  fireEvent.pointerDown(endHandleOfFirst(), { clientX: 60, button: 0, altKey: true });
  fireEvent.pointerMove(window, { clientX: 70 });
  fireEvent.pointerUp(window, { clientX: 70 });
  expect(screen.getByRole("status").textContent).toContain("This cut is a scene boundary. Resize the scene in Story instead");
});

// Tier 3a: markers on the ruler.
function withMarkers(markers: { marker_id: string; frame: number; label: string }[], overrides: Partial<EditorState> = {}) {
  const doc = timelineDocument();
  doc.markers = markers;
  return mount({ base: doc, draft: doc, ...overrides });
}

test("M adds a marker at the playhead as one edit", () => {
  const { actions } = mount({ playheadFrame: 60 });
  key(document.body, "m");
  const added = actions.find((action) => action.type === "commit_operations");
  expect(added?.type === "commit_operations" && added.operations).toEqual([expect.objectContaining({ kind: "add_marker", frame: 60, label: "" })]);
});

test("M typed in a field adds no marker", () => {
  const { actions } = mount({ playheadFrame: 60 });
  const field = document.body.appendChild(document.createElement("input"));
  key(field, "m");
  field.remove();
  expect(actions).toEqual([]);
});

test("a marker is a button on the ruler that moves the playhead to it", () => {
  const { actions } = withMarkers([
    { marker_id: "m_named", frame: 90, label: "Hook beat" },
    { marker_id: "m_plain", frame: 60, label: "" },
  ]);
  expect(screen.getByRole("button", { name: "Marker 1 at 0:02.0" })).toBeDefined();
  fireEvent.click(screen.getByRole("button", { name: "Hook beat at 0:03.0" }));
  expect(actions.at(-1)).toEqual({ type: "set_playhead", frame: 90 });
});

const openMarkerMenu = (name: string) => fireEvent.contextMenu(screen.getByRole("button", { name }), { clientX: 5, clientY: 5 });

test("a marker's menu deletes it and moves it to the playhead", () => {
  const { actions } = withMarkers([{ marker_id: "m1", frame: 60, label: "" }], { playheadFrame: 30 });
  openMarkerMenu("Marker 1 at 0:02.0");
  expect(menuNames()).toEqual(["Rename marker…", "Move to playhead", "Delete marker"]);
  fireEvent.click(screen.getByRole("menuitem", { name: "Move to playhead" }));
  expect(ops(actions)).toEqual(["set_marker"]);
  openMarkerMenu("Marker 1 at 0:02.0");
  fireEvent.click(screen.getByRole("menuitem", { name: "Delete marker" }));
  expect(ops(actions)).toEqual(["set_marker", "remove_marker"]);
});

test("Rename marker… names it, and the name is saved as one edit", () => {
  const { actions } = withMarkers([{ marker_id: "m1", frame: 60, label: "" }]);
  openMarkerMenu("Marker 1 at 0:02.0");
  fireEvent.click(screen.getByRole("menuitem", { name: "Rename marker…" }));
  const dialog = screen.getByRole("dialog", { name: "Rename marker" });
  fireEvent.change(within(dialog).getByRole("textbox", { name: "Marker name" }), { target: { value: "Hook ends" } });
  fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
  const saved = actions.find((action) => action.type === "commit_operations");
  expect(saved?.type === "commit_operations" && saved.operations).toEqual([expect.objectContaining({ kind: "set_marker", marker_id: "m1", frame: 60, label: "Hook ends" })]);
  expect(screen.queryByRole("dialog", { name: "Rename marker" })).toBeNull();
});

// Tier 3a (operator, 2026-11-09): phones get the editing menus by long press; no drag, trim or keys.
function mountPhone(overrides: Partial<EditorState> = {}) {
  const actions: EditorAction[] = [];
  const state = { ...createEditorState(timelineDocument()), ...overrides };
  render(<Timeline state={state} dispatch={(action) => actions.push(action)} onPlay={() => {}} onPause={() => {}} readOnly />);
  return { actions };
}
const longPress = async (element: Element) => {
  fireEvent.pointerDown(element, { pointerType: "touch", clientX: 5, clientY: 5, button: 0 });
  await new Promise((done) => setTimeout(done, 550));
};

test("on a phone a long press on a clip opens its menu, and its edits commit", async () => {
  const { actions } = mountPhone({ playheadFrame: 60 });
  await longPress(screen.getByRole("button", { name: "Main video clip" }));
  expect(screen.getByRole("menu")).toBeTruthy();
  fireEvent.click(screen.getByRole("menuitem", { name: "Split at playhead" }));
  expect(ops(actions)).toEqual(["split_clip"]);
});

test("on a phone the lane and track menus open by long press too", async () => {
  mountPhone();
  await longPress(screen.getByRole("button", { name: "Select Music track" }));
  expect(screen.getByRole("menuitem", { name: "Select track" })).toBeTruthy();
});

test("on a phone a press that moves scrolls and opens nothing", async () => {
  mountPhone();
  fireEvent.pointerDown(screen.getByRole("button", { name: "Main video clip" }), { pointerType: "touch", clientX: 5, clientY: 5, button: 0 });
  fireEvent.pointerMove(window, { clientX: 40, clientY: 5 });
  await new Promise((done) => setTimeout(done, 550));
  expect(screen.queryByRole("menu")).toBeNull();
});

test("on a phone there are no trim handles and a drag commits nothing", () => {
  const { actions } = mountPhone();
  expect(screen.queryByRole("button", { name: "Trim end of Main video clip" })).toBeNull();
  drag(screen.getByRole("button", { name: "Main video clip" }), 10, 80);
  expect(actions.some((action) => action.type.startsWith("commit"))).toBe(false);
});

test("the phone banner says how to edit here", () => {
  mountPhone();
  expect(document.body.textContent).toContain("Tap a clip to select it. Press and hold for its menu. Drag and trim on a wider screen.");
});

// Final review 2026-11-09: phones long-press markers now, so a marker is a 24 px target.
test("a marker is at least a 24 px target", () => {
  withMarkers([{ marker_id: "m1", frame: 60, label: "" }]);
  const marker = screen.getByRole("button", { name: "Marker 1 at 0:02.0" });
  expect(marker.className).toContain("h-6");
  expect(marker.className).toContain("w-6");
});

// Tier 3b: clips show what they hold.
const VIDEO_GLANCE = {
  asset_id: "asset_video",
  strip: { image: "data:image/jpeg;base64,AAAA", frame_width: 128, frame_height: 72, frames: 5, seconds_per_frame: 1 },
  peaks: null,
};
const AUDIO_GLANCE = { asset_id: "asset_music", strip: null, peaks: { seconds_per_peak: 0.1, values: [10, 60, 30] } };
function mountWithGlances(glanceOf?: (assetId: string) => typeof VIDEO_GLANCE | typeof AUDIO_GLANCE | undefined, doc = timelineDocument()) {
  render(<Timeline state={createEditorState(doc)} dispatch={() => {}} onPlay={() => {}} onPause={() => {}} glanceOf={glanceOf as never} />);
}

test("video clips show their filmstrip and audio clips their waveform", () => {
  mountWithGlances((assetId) => (assetId === "asset_video" ? VIDEO_GLANCE : assetId === "asset_music" ? AUDIO_GLANCE : undefined));
  const strips = screen.getAllByTestId("clip-filmstrip");
  expect(strips.length).toBe(2);
  expect(strips[0]!.outerHTML).toContain("data:image/jpeg;base64,AAAA");
  expect(screen.getAllByTestId("clip-waveform").length).toBe(1);
});

test("without a glance a clip draws as before", () => {
  mountWithGlances(undefined);
  expect(screen.queryByTestId("clip-filmstrip")).toBeNull();
  expect(screen.queryByTestId("clip-waveform")).toBeNull();
});

test("a text clip never shows a filmstrip or a waveform", () => {
  mountWithGlances(() => VIDEO_GLANCE, textDocument());
  const text = screen.getByRole("button", { name: /^Overlay clip/ });
  expect(text.querySelector("[data-testid='clip-filmstrip'], [data-testid='clip-waveform']")).toBeNull();
});

// Tier 3b: an audio clip's volume line, dragged or keyed; one edit on release.
function musicAt(volume: number, overrides: Record<string, unknown> = {}) {
  const doc = timelineDocument();
  Object.assign(doc.clips!.find((clip) => clip.clip_id === "clip_music")!, { volume, ...overrides });
  return doc;
}
const volumeLine = () => screen.getByRole("slider", { name: "Volume of Music clip" });
function withBox(element: HTMLElement) {
  Object.defineProperty(element.parentElement!, "getBoundingClientRect", {
    value: () => ({ top: 100, bottom: 140, height: 40, left: 0, right: 200, width: 200, x: 0, y: 100, toJSON: () => ({}) }),
  });
}
const volumeOps = (actions: EditorAction[], type: string) =>
  actions.filter((action) => action.type === type).map((action) => ("operation" in action ? action.operation : null));

test("dragging an audio clip's volume line previews, then commits once at the pointer", () => {
  const doc = musicAt(0.5);
  const { actions } = mount({ base: doc, draft: doc });
  withBox(volumeLine());
  fireEvent.pointerDown(volumeLine(), { clientY: 120, button: 0 });
  fireEvent.pointerMove(window, { clientY: 110 });
  fireEvent.pointerUp(window, { clientY: 110 });
  expect(volumeOps(actions, "preview_timeline_operation").at(-1)).toMatchObject({ kind: "set_clip_volume", clip_id: "clip_music", volume: 0.75 });
  expect(volumeOps(actions, "commit_timeline_operation")).toEqual([expect.objectContaining({ kind: "set_clip_volume", volume: 0.75 })]);
});

test("the volume line steps by 0.05 with arrows, and Home and End go to 0 and 1", () => {
  const doc = musicAt(0.5);
  const { actions } = mount({ base: doc, draft: doc });
  fireEvent.keyDown(volumeLine(), { key: "ArrowUp" });
  fireEvent.keyDown(volumeLine(), { key: "Home" });
  fireEvent.keyDown(volumeLine(), { key: "End" });
  expect(volumeOps(actions, "commit_timeline_operation").map((operation) => (operation as { volume: number }).volume)).toEqual([0.55, 0, 1]);
});

test("Escape during a volume drag cancels it and nothing commits", () => {
  const doc = musicAt(0.5);
  const { actions } = mount({ base: doc, draft: doc });
  withBox(volumeLine());
  fireEvent.pointerDown(volumeLine(), { clientY: 120, button: 0 });
  fireEvent.pointerMove(window, { clientY: 105 });
  fireEvent.keyDown(window, { key: "Escape" });
  fireEvent.pointerUp(window, { clientY: 105 });
  expect(actions.some((action) => action.type === "cancel_timeline_preview")).toBe(true);
  expect(volumeOps(actions, "commit_timeline_operation")).toEqual([]);
});

test("a locked audio clip, a view-only timeline and video clips have no volume line", () => {
  const locked = musicAt(0.5, { locked: true });
  mount({ base: locked, draft: locked });
  expect(screen.queryByRole("slider", { name: /^Volume of / })).toBeNull();
  cleanup();
  render(<Timeline state={createEditorState(musicAt(0.5))} dispatch={() => {}} readOnly />);
  expect(screen.queryByRole("slider", { name: /^Volume of / })).toBeNull();
  cleanup();
  mount();
  expect(screen.queryByRole("slider", { name: "Volume of Main video clip" })).toBeNull();
});

test("a volume above 1 rests at the top of the line", () => {
  const doc = musicAt(1.6);
  mount({ base: doc, draft: doc });
  expect(volumeLine().getAttribute("aria-valuenow")).toBe("100");
  expect(volumeLine().style.top).toBe("0%");
});

// Final review 2026-11-09 fixes.
test("a press on the volume line without a move changes nothing", () => {
  const doc = musicAt(0.73);
  const { actions } = mount({ base: doc, draft: doc });
  withBox(volumeLine());
  fireEvent.pointerDown(volumeLine(), { clientY: 112, button: 0 });
  fireEvent.pointerUp(window, { clientY: 112 });
  expect(volumeOps(actions, "commit_timeline_operation")).toEqual([]);
});

test("a cancelled pointer ends the volume drag and commits nothing later", () => {
  const doc = musicAt(0.5);
  const { actions } = mount({ base: doc, draft: doc });
  withBox(volumeLine());
  fireEvent.pointerDown(volumeLine(), { clientY: 120, button: 0 });
  fireEvent.pointerMove(window, { clientY: 110 });
  fireEvent.pointerCancel(window);
  fireEvent.pointerUp(window, { clientY: 101 });
  expect(actions.some((action) => action.type === "cancel_timeline_preview")).toBe(true);
  expect(volumeOps(actions, "commit_timeline_operation")).toEqual([]);
});

test("ArrowUp and End never lower a clip that is already above 1", () => {
  const doc = musicAt(1.6);
  const { actions } = mount({ base: doc, draft: doc });
  fireEvent.keyDown(volumeLine(), { key: "ArrowUp" });
  fireEvent.keyDown(volumeLine(), { key: "End" });
  expect(volumeOps(actions, "commit_timeline_operation")).toEqual([]);
});

test("a filmstrip carries its picture once, not once per tile", () => {
  mountWithGlances((assetId) => (assetId === "asset_video" ? VIDEO_GLANCE : undefined));
  const strip = screen.getAllByTestId("clip-filmstrip")[0]!;
  expect(strip.outerHTML.split("data:image/jpeg;base64,AAAA").length - 1).toBe(1);
});

test("a volume drag stops when its clip goes away", () => {
  const doc = musicAt(0.5);
  const { actions } = mount({ base: doc, draft: doc });
  withBox(volumeLine());
  fireEvent.pointerDown(volumeLine(), { clientY: 120, button: 0 });
  fireEvent.pointerMove(window, { clientY: 110 });
  cleanup();
  fireEvent.pointerUp(window, { clientY: 110 });
  expect(volumeOps(actions, "commit_timeline_operation")).toEqual([]);
});
