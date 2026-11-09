/// <reference types="bun-types" />

import { afterEach, expect, test } from "bun:test";
import { cleanup, fireEvent, screen } from "@testing-library/react";

import { render } from "@/test-render";

import type { EditDocumentOperation } from "@/api/control-plane";
import { setPositionPreset } from "./story/story_edits";
import { TimelineInspector } from "./TimelineInspector";
import { timelineDocument, typedTimelineDocument } from "./timeline-test-fixtures";

afterEach(cleanup);

/** Render the inspector over one selection and collect the operations it emits. */
function mount(
  selection: { clipId?: string; trackId?: string },
  document = timelineDocument(),
) {
  const operations: EditDocumentOperation[] = [];
  render(
    <TimelineInspector
      document={document}
      selectedClipId={selection.clipId ?? ""}
      selectedTrackId={selection.trackId ?? ""}
      onOperation={(operation) => operations.push(operation)}
    />,
  );
  return { operations };
}

const payload = (operation: EditDocumentOperation) => ({ ...operation, operation_id: "op" });

test("asks for a selection when nothing is selected", () => {
  mount({});
  expect(screen.getByText("Select a clip or track to edit it")).toBeDefined();
});

test("trims a media clip through typed operations", () => {
  const { operations } = mount({ clipId: "clip_main" });
  fireEvent.change(screen.getByLabelText("Start frame"), { target: { value: "20" } });
  fireEvent.change(screen.getByLabelText("End frame"), { target: { value: "100" } });

  expect(operations.map(payload)).toEqual([
    { kind: "trim_clip_start", operation_id: "op", clip_id: "clip_main", from_frame: 20 },
    { kind: "trim_clip_end", operation_id: "op", clip_id: "clip_main", end_frame: 100 },
  ]);
});

test("sets the volume of an audio clip", () => {
  const { operations } = mount({ clipId: "clip_music" });
  fireEvent.change(screen.getByLabelText("Volume"), { target: { value: "0.5" } });

  expect(payload(operations[0]!)).toEqual({
    kind: "set_clip_volume",
    operation_id: "op",
    clip_id: "clip_music",
    volume: 0.5,
  });
  expect(screen.queryByLabelText("Volume")).not.toBeNull();
});

test("keeps volume away from a clip that carries no audio", () => {
  mount({ clipId: "clip_main" });
  expect(screen.queryByLabelText("Volume")).toBeNull();
});

test("hides, locks, and re-owns the selected clip", () => {
  const { operations } = mount({ clipId: "clip_main" });
  fireEvent.click(screen.getByLabelText("Hidden"));
  fireEvent.click(screen.getByLabelText("Locked"));
  fireEvent.change(screen.getByLabelText("Edited by"), { target: { value: "user_edited" } });

  expect(operations.map(payload)).toEqual([
    { kind: "set_clip_hidden", operation_id: "op", clip_id: "clip_main", hidden: true },
    { kind: "set_clip_locked", operation_id: "op", clip_id: "clip_main", locked: true },
    {
      kind: "set_ownership",
      operation_id: "op",
      clip_id: "clip_main",
      ownership: "user_edited",
    },
  ]);
});

test("keeps a locked track read-only apart from its own lock", () => {
  mount({ trackId: "track_captions" });
  expect(screen.getByLabelText("Hidden").hasAttribute("disabled")).toBe(true);
  expect(screen.getByLabelText("Locked").hasAttribute("disabled")).toBe(false);
  expect(screen.queryByRole("button", { name: "Remove empty track" })).toBeNull();
});

test("edits the selected track without touching its clips", () => {
  const { operations } = mount({ trackId: "track_music" });
  fireEvent.click(screen.getByLabelText("Hidden"));
  fireEvent.click(screen.getByLabelText("Muted"));
  fireEvent.click(screen.getByLabelText("Locked"));

  expect(operations.map(payload)).toEqual([
    { kind: "set_track_visibility", operation_id: "op", track_id: "track_music", hidden: true },
    { kind: "set_track_muted", operation_id: "op", track_id: "track_music", muted: true },
    { kind: "set_track_locked", operation_id: "op", track_id: "track_music", locked: true },
  ]);
});

test("offers to remove a track once it is empty and unlocked", () => {
  const unlocked = timelineDocument();
  unlocked.tracks[3]!.locked = false;
  const { operations } = mount({ trackId: "track_captions" }, unlocked);
  fireEvent.click(screen.getByRole("button", { name: "Remove empty track" }));
  expect(payload(operations[0]!)).toEqual({
    kind: "remove_empty_track",
    operation_id: "op",
    track_id: "track_captions",
  });
});

test("shows the newly selected clip's values without remounting", () => {
  const document = typedTimelineDocument();
  const view = render(
    <TimelineInspector
      document={document}
      selectedClipId="clip_a"
      selectedTrackId=""
      onOperation={() => {}}
    />,
  );
  expect((screen.getByLabelText("Start frame") as HTMLInputElement).value).toBe("0");

  view.rerender(
    <TimelineInspector
      document={document}
      selectedClipId="clip_b"
      selectedTrackId=""
      onOperation={() => {}}
    />,
  );

  expect((screen.getByLabelText("Start frame") as HTMLInputElement).value).toBe("90");
  expect((screen.getByLabelText("End frame") as HTMLInputElement).value).toBe("210");
  expect((screen.getByLabelText("Fit") as HTMLInputElement).value).toBe("contain");
  // Since Tier 2 crop and position are editable fields in percent (crop 0.1, 0.2, 0.5, 0.6).
  const value = (name: string) => (screen.getByLabelText(name) as HTMLInputElement).value;
  expect(["Crop left", "Crop top", "Crop right", "Crop bottom"].map(value)).toEqual(["10", "20", "40", "20"]);
  expect(["Position X", "Position Y", "Scale"].map(value)).toEqual(["25", "-50", "150"]);
});

test("emits an edit against the clip that is selected now", () => {
  const document = typedTimelineDocument();
  const operations: EditDocumentOperation[] = [];
  const view = render(
    <TimelineInspector
      document={document}
      selectedClipId="clip_a"
      selectedTrackId=""
      onOperation={(operation) => operations.push(operation)}
    />,
  );
  view.rerender(
    <TimelineInspector
      document={document}
      selectedClipId="clip_b"
      selectedTrackId=""
      onOperation={(operation) => operations.push(operation)}
    />,
  );
  fireEvent.change(screen.getByLabelText("Start frame"), { target: { value: "95" } });

  expect(operations.map(payload)).toEqual([
    { kind: "trim_clip_start", operation_id: "op", clip_id: "clip_b", from_frame: 95 },
  ]);
});

test("reports an audio clip's volume and fades for the current selection", () => {
  const document = typedTimelineDocument();
  render(
    <TimelineInspector
      document={document}
      selectedClipId="clip_audio"
      selectedTrackId=""
      onOperation={() => {}}
    />,
  );

  expect((screen.getByLabelText("Volume") as HTMLInputElement).value).toBe("0.4");
  // Fades read in seconds since Tier 2 (12 and 24 frames at 30 fps).
  expect((screen.getByLabelText("Fade in (seconds)") as HTMLInputElement).value).toBe("0.4");
  expect((screen.getByLabelText("Fade out (seconds)") as HTMLInputElement).value).toBe("0.8");
});

test("reports persisted overlay and caption fields as read-only values", () => {
  const document = typedTimelineDocument();
  const view = render(
    <TimelineInspector
      document={document}
      selectedClipId="clip_overlay"
      selectedTrackId=""
      onOperation={() => {}}
    />,
  );

  const preset = screen.getByLabelText("Overlay preset") as HTMLInputElement;
  expect(preset.value).toBe("lower_third");
  expect(preset.disabled).toBe(true);
  expect((screen.getByLabelText("Overlay text") as HTMLInputElement).value).toBe("Headline");
  expect((screen.getByLabelText("Overlay accent") as HTMLInputElement).value).toBe("accent_primary");

  view.rerender(
    <TimelineInspector
      document={document}
      selectedClipId="clip_caption"
      selectedTrackId=""
      onOperation={() => {}}
    />,
  );

  expect((screen.getByLabelText("Caption style") as HTMLInputElement).value).toBe("caption_default");
  expect((screen.getByLabelText("Caption cues") as HTMLInputElement).value).toBe(
    "0–30 First cue · 30–90 Second cue",
  );
});


/** The fixture with one subtitle band on its main clip, blur switched as given. */
function subtitled(enabled: boolean) {
  const document = timelineDocument();
  const main = document.clips!.find((clip) => clip.clip_id === "clip_main")!;
  Object.assign(main, {
    blur_enabled: enabled,
    blur_regions: [{ x: 0.1, y: 0.65, w: 0.8, h: 0.09, from_frame: null, to_frame: null }],
  });
  return document;
}

test("blur subtitles and mute emits both operations in order", () => {
  const { operations } = mount({ clipId: "clip_main" }, subtitled(false));
  expect(screen.getByText("Subtitles detected (1 region)")).toBeDefined();
  fireEvent.click(screen.getByRole("button", { name: "Blur subtitles and mute" }));
  expect(operations.map(payload)).toEqual([
    { kind: "set_clip_blur", operation_id: "op", clip_id: "clip_main", blur_enabled: true },
    { kind: "set_track_muted", operation_id: "op", track_id: "track_main", muted: true },
  ]);
});

test("remove blur leaves the track mute alone", () => {
  const { operations } = mount({ clipId: "clip_main" }, subtitled(true));
  fireEvent.click(screen.getByRole("button", { name: "Remove blur" }));
  expect(operations.map(payload)).toEqual([
    { kind: "set_clip_blur", operation_id: "op", clip_id: "clip_main", blur_enabled: false },
  ]);
});

test("no regions, no blur control", () => {
  mount({ clipId: "clip_main" });
  expect(screen.queryByText(/Subtitles detected/)).toBeNull();
  expect(screen.queryByRole("button", { name: "Blur subtitles and mute" })).toBeNull();
});

test("remove blur is disabled on a locked track", () => {
  const document = subtitled(true);
  document.tracks.find((track) => track.track_id === "track_main")!.locked = true;
  mount({ clipId: "clip_main" }, document);
  expect((screen.getByRole("button", { name: "Remove blur" }) as HTMLButtonElement).disabled).toBe(true);
});

test("the heading names the clip by what it is and where it sits", () => {
  mount({ clipId: "clip_caption" }, typedTimelineDocument());
  expect(screen.getByRole("heading", { level: 2 }).textContent).toBe("First cue");
  expect(screen.getByText("Captions track")).toBeDefined();
});

test("a clip's fields come in timing, transform and clip sections", () => {
  mount({ clipId: "clip_b" }, typedTimelineDocument());
  for (const name of ["Timing", "Transform", "Clip"]) {
    expect(screen.getByRole("group", { name })).toBeDefined();
  }
  expect(screen.getByRole("group", { name: "Timing" }).textContent).toContain("0:03.0");
  expect(screen.getByRole("group", { name: "Timing" }).textContent).toContain("0:07.0");
});

test("position presets place a clip the way Story mode does", () => {
  const document = typedTimelineDocument();
  const { operations } = mount({ clipId: "clip_b" }, document);
  fireEvent.click(screen.getByRole("button", { name: "Top" }));
  expect(operations.map(payload)).toEqual(
    setPositionPreset(document, ["clip_b"], "top").map(payload),
  );
});

test("a clip with no sound of its own says where the sound is", () => {
  mount({ clipId: "clip_caption" }, typedTimelineDocument());
  const audio = screen.getByRole("group", { name: "Audio" });
  expect(audio.textContent).toContain("This clip has no sound. Select a narration or music clip.");
  expect(screen.queryByLabelText("Volume")).toBeNull();
});

test("the timeline inspector title is the clip label", () => {
  // Studio shell v2 (spec 2026-11-01, goal 4): Studio passes kind-and-source labels in.
  render(
    <TimelineInspector
      document={timelineDocument()}
      selectedClipId="clip_main"
      selectedTrackId=""
      onOperation={() => {}}
      labelOf={(clip) => (clip.clip_id === "clip_main" ? "Footage · @OfficialiNews" : "Other")}
    />,
  );

  expect(screen.getByRole("heading", { level: 2, name: "Footage · @OfficialiNews" })).toBeDefined();
});

test("the inspector lists the selected clip's issues", () => {
  // Studio shell v2 (spec 2026-11-01, goal 7): a late main clip leaves a gap before it.
  const document = timelineDocument();
  document.clips![0]!.from_frame = 30;
  mount({ clipId: "clip_main" }, document);

  const issues = screen.getByRole("group", { name: "Issues · 1" });
  expect(issues.textContent).toContain("Main video: a clip starts after a gap");
});

// Spec 2026-11-08 §5.1: time as time, frames beside it; tracks in plain names.
test("start and end are typed as time and land as moves and trims", () => {
  const { operations } = mount({ clipId: "clip_main" });
  const start = screen.getByRole("textbox", { name: "Start time" }) as HTMLInputElement;
  const end = screen.getByRole("textbox", { name: "End time" }) as HTMLInputElement;
  expect(start.value).toBe("0:00.0");
  expect(end.value).toBe("0:04.0");
  fireEvent.change(start, { target: { value: "0:01.0" } });
  fireEvent.keyDown(start, { key: "Enter" });
  fireEvent.change(end, { target: { value: "0:03.0" } });
  fireEvent.blur(end);
  expect(operations.map(payload)).toEqual([
    { kind: "move_clip", operation_id: "op", clip_id: "clip_main", target_track_id: "track_main", from_frame: 30, ripple: false },
    { kind: "trim_clip_end", operation_id: "op", clip_id: "clip_main", end_frame: 90 },
  ]);
  expect(screen.getByRole("spinbutton", { name: "Start frame" })).toBeDefined();
});

test("an unreadable time changes nothing and shows the clip's time again", () => {
  const { operations } = mount({ clipId: "clip_main" });
  const start = screen.getByRole("textbox", { name: "Start time" }) as HTMLInputElement;
  fireEvent.change(start, { target: { value: "soon" } });
  fireEvent.keyDown(start, { key: "Enter" });
  expect(operations).toEqual([]);
  expect(start.value).toBe("0:00.0");
});

test("a selected track reads by its plain name, never its raw kind", () => {
  mount({ trackId: "track_main" });
  expect(screen.getByRole("heading", { name: "Main video" })).toBeDefined();
  expect(screen.queryByText("main_video")).toBeNull();
});

test("who edits a clip reads in plain words", () => {
  mount({ clipId: "clip_main" });
  const select = screen.getByLabelText("Edited by") as HTMLSelectElement;
  expect([...select.options].map((option) => option.textContent)).toEqual(["Thoth", "You", "Nobody (locked)"]);
});

// Final review 2026-11-08 #2: frame 7 shows as 0:00.2, which reads back as frame 6.
test("leaving a time field untouched changes nothing, off the tenth-second grid too", () => {
  const document = timelineDocument();
  const main = document.clips!.find((clip) => clip.clip_id === "clip_main")!;
  main.from_frame = 7;
  main.duration_in_frames = 100;
  const { operations } = mount({ clipId: "clip_main" }, document);
  fireEvent.blur(screen.getByRole("textbox", { name: "Start time" }));
  fireEvent.keyDown(screen.getByRole("textbox", { name: "End time" }), { key: "Enter" });
  expect(operations).toEqual([]);
});

// Tier 2 (spec 2026-11-08 §6): Fit, Crop, Position and fades are editable.
const field = (name: string) => screen.getByLabelText(name) as HTMLInputElement;
const typeAndLeave = (name: string, value: string) => {
  fireEvent.change(field(name), { target: { value } });
  fireEvent.blur(field(name));
};

test("Fit is a choice that commits set_clip_fit", () => {
  const { operations } = mount({ clipId: "clip_main" });
  fireEvent.change(screen.getByRole("combobox", { name: "Fit" }), { target: { value: "contain" } });
  expect(operations.map(payload)).toEqual([{ kind: "set_clip_fit", operation_id: "op", clip_id: "clip_main", fit: "contain" }]);
});

test("crop fields commit a crop in fractions", () => {
  const { operations } = mount({ clipId: "clip_main" });
  expect(screen.getByLabelText("Crop")).toBeDefined();
  typeAndLeave("Crop left", "10");
  expect(operations.map(payload)).toEqual([
    { kind: "set_clip_crop", operation_id: "op", clip_id: "clip_main", crop: { left: 0.1, top: 0, width: 0.9, height: 1 } },
  ]);
});

test("a crop that leaves no picture is refused in place", () => {
  const document = timelineDocument();
  Object.assign(document.clips!.find((clip) => clip.clip_id === "clip_main")!, { crop: { left: 0.6, top: 0, width: 0.4, height: 1 } });
  const { operations } = mount({ clipId: "clip_main" }, document);
  typeAndLeave("Crop right", "50");
  expect(operations).toEqual([]);
  expect(screen.getByRole("alert").textContent).toContain("Crop leaves no picture");
});

test("Reset crop sends no crop", () => {
  const document = timelineDocument();
  Object.assign(document.clips!.find((clip) => clip.clip_id === "clip_main")!, { crop: { left: 0.1, top: 0, width: 0.9, height: 1 } });
  const { operations } = mount({ clipId: "clip_main" }, document);
  fireEvent.click(screen.getByRole("button", { name: "Reset crop" }));
  expect(operations.map(payload)).toEqual([{ kind: "set_clip_crop", operation_id: "op", clip_id: "clip_main", crop: null }]);
});

test("position and scale commit set_clip_position", () => {
  const { operations } = mount({ clipId: "clip_main" });
  typeAndLeave("Position X", "25");
  typeAndLeave("Scale", "150");
  expect(operations.map(payload)).toEqual([
    { kind: "set_clip_position", operation_id: "op", clip_id: "clip_main", position: { x: 0.25, y: 0, scale: 1 } },
    { kind: "set_clip_position", operation_id: "op", clip_id: "clip_main", position: { x: 0, y: 0, scale: 1.5 } },
  ]);
});

test("fades commit set_clip_fades in frames", () => {
  const { operations } = mount({ clipId: "clip_main" });
  typeAndLeave("Fade in (seconds)", "0.5");
  expect(operations.map(payload)).toEqual([
    { kind: "set_clip_fades", operation_id: "op", clip_id: "clip_main", fade_in_frames: 15, fade_out_frames: 0 },
  ]);
});

test("a fade longer than the clip is refused in place", () => {
  const { operations } = mount({ clipId: "clip_main" });
  typeAndLeave("Fade out (seconds)", "9");
  expect(operations).toEqual([]);
  expect(screen.getByRole("alert").textContent).toContain("Fades are longer than the clip");
});

test("an untouched field commits nothing on blur", () => {
  const { operations } = mount({ clipId: "clip_main" });
  for (const name of ["Crop left", "Position X", "Scale", "Fade in (seconds)"]) fireEvent.blur(field(name));
  expect(operations).toEqual([]);
});

test("a locked clip shows Fit, Crop, Position and fades read-only", () => {
  mount({ clipId: "clip_locked" });
  expect((screen.getByRole("combobox", { name: "Fit" }) as HTMLSelectElement).disabled).toBe(true);
  for (const name of ["Crop left", "Position X", "Scale", "Fade in (seconds)"]) expect(field(name).disabled).toBe(true);
});

// Tier 1 review leftovers (2026-11-08): a typed time the editor refuses shows the clip's real time again.
test("a refused start time returns to the clip's real time", () => {
  mount({ clipId: "clip_main" });
  const start = screen.getByLabelText("Start time") as HTMLInputElement;
  const before = start.value;
  fireEvent.change(start, { target: { value: "0:02" } });
  fireEvent.blur(start);
  // The document did not change (the parent refused the move), so the field shows the real time.
  expect(start.value).toBe(before);
});

// Tier 3a (spec 2026-11-08 section 7): a clip's speed, from the presets.
const withAsset = (fields: Record<string, unknown>) => {
  const document = timelineDocument();
  Object.assign(document.asset_refs!.find((ref) => ref.asset_id === "asset_video")!, fields);
  return document;
};

test("Speed is a choice of presets that commits set_clip_speed", () => {
  const { operations } = mount({ clipId: "clip_main" });
  const speed = screen.getByRole("combobox", { name: "Speed" });
  expect(Array.from((speed as HTMLSelectElement).options).map((option) => option.textContent)).toEqual(["0.25×", "0.5×", "0.75×", "1×", "1.25×", "1.5×", "2×", "3×", "4×"]);
  fireEvent.change(speed, { target: { value: "2" } });
  expect(operations.map(payload)).toEqual([{ kind: "set_clip_speed", operation_id: "op", clip_id: "clip_main", speed: 2 }]);
});

test("an audio clip has a Speed too", () => {
  const { operations } = mount({ clipId: "clip_music" });
  fireEvent.change(screen.getByRole("combobox", { name: "Speed" }), { target: { value: "0.5" } });
  expect(operations.map(payload)).toEqual([{ kind: "set_clip_speed", operation_id: "op", clip_id: "clip_music", speed: 0.5 }]);
});

test("an image clip has no Speed", () => {
  mount({ clipId: "clip_main" }, withAsset({ kind: "image" }));
  expect(screen.queryByRole("combobox", { name: "Speed" })).toBeNull();
});

test("a speed the source cannot feed is refused in place", () => {
  // clip_main is 120 frames long; at 2x it needs 240 frames of a 200-frame source.
  const { operations } = mount({ clipId: "clip_main" }, withAsset({ duration_in_frames: 200 }));
  fireEvent.change(screen.getByRole("combobox", { name: "Speed" }), { target: { value: "2" } });
  expect(operations).toEqual([]);
  expect(screen.getByRole("alert").textContent).toContain("The source is too short for this speed");
});

// Tier 3a: slip by number, the keyboard path to Alt+drag.
test("Source start in seconds commits slip_clip", () => {
  const { operations } = mount({ clipId: "clip_main" }, withAsset({ duration_in_frames: 200 }));
  typeAndLeave("Source start (seconds)", "1");
  expect(operations.map(payload)).toEqual([{ kind: "slip_clip", operation_id: "op", clip_id: "clip_main", source_from_frame: 30 }]);
});

test("a source start past what the source holds is refused in place", () => {
  // clip_main is 120 frames long on a 200-frame source: 80 frames is the latest start, 2.6 s in tenths.
  const { operations } = mount({ clipId: "clip_main" }, withAsset({ duration_in_frames: 200 }));
  typeAndLeave("Source start (seconds)", "5");
  expect(operations).toEqual([]);
  expect(screen.getByRole("alert").textContent).toContain("The source start can be at most 2.6 s");
});

test("an audio clip has a Source start too", () => {
  mount({ clipId: "clip_music" });
  expect(screen.getByLabelText("Source start (seconds)")).toBeDefined();
});

test("an image clip has no Source start", () => {
  mount({ clipId: "clip_main" }, withAsset({ kind: "image" }));
  expect(screen.queryByLabelText("Source start (seconds)")).toBeNull();
});

// Carried Tier 2 minor (operator, 2026-11-09): a refused value says what would be accepted.
test.each([
  ["Crop left", "150", "Enter a number from 0 to 100"],
  ["Position X", "999", "Enter a number from -100 to 100"],
  ["Scale", "0.5", "Enter a number from 1 to 400"],
  ["Fade in (seconds)", "-1", "Enter a number from 0 to 10"],
  ["Crop top", "abc", "Enter a number from 0 to 100"],
])("%s refuses %s and says what it takes", (name, value, message) => {
  const { operations } = mount({ clipId: "clip_main" });
  typeAndLeave(name, value);
  expect(operations).toEqual([]);
  expect(screen.getByRole("alert").textContent).toContain(message);
});

test("a refusal shows above the fields, not under the fades", () => {
  mount({ clipId: "clip_main" });
  typeAndLeave("Crop left", "150");
  const following = screen.getByRole("alert").compareDocumentPosition(field("Fit" as string)) & Node.DOCUMENT_POSITION_FOLLOWING;
  expect(following).toBeTruthy();
});

// Studio effects layer (spec 2026-11-09): the Effects section for a video clip.
function mountEffects(document = timelineDocument(), playheadFrame = 0) {
  const operations: EditDocumentOperation[] = [];
  render(
    <TimelineInspector
      document={document}
      selectedClipId="clip_main"
      selectedTrackId=""
      playheadFrame={playheadFrame}
      onOperation={(operation) => operations.push(operation)}
    />,
  );
  return { operations };
}

const withMain = (fields: Record<string, unknown>) => {
  const document = timelineDocument();
  Object.assign(document.clips!.find((clip) => clip.clip_id === "clip_main")!, fields);
  return document;
};

test("choosing Blur-fill sends set_clip_background", () => {
  const { operations } = mountEffects();
  fireEvent.change(screen.getByLabelText("Background"), { target: { value: "blur_fill" } });
  expect(payload(operations[0]!)).toEqual({ kind: "set_clip_background", operation_id: "op", clip_id: "clip_main", background: "blur_fill" });
});

test("releasing Dim at 40% sends set_clip_dim 0.4", () => {
  const { operations } = mountEffects();
  const dim = screen.getByLabelText("Dim");
  fireEvent.change(dim, { target: { value: "40" } });
  expect(operations).toHaveLength(0);
  fireEvent.pointerUp(dim);
  expect(payload(operations[0]!)).toEqual({ kind: "set_clip_dim", operation_id: "op", clip_id: "clip_main", dim: 0.4 });
});

test("Push in sends set_clip_moves with the preset", () => {
  const { operations } = mountEffects();
  fireEvent.click(screen.getByRole("button", { name: "Push in" }));
  expect(payload(operations[0]!)).toEqual({
    kind: "set_clip_moves",
    operation_id: "op",
    clip_id: "clip_main",
    moves: [
      { frame: 0, scale: 1, x: 0, y: 0, ease: "linear" },
      { frame: 119, scale: 1.12, x: 0, y: 0, ease: "linear" },
    ],
  });
});

test("Punch in uses the playhead", () => {
  const { operations } = mountEffects(timelineDocument(), 60);
  fireEvent.click(screen.getByRole("button", { name: "Punch in at playhead" }));
  const moves = (operations[0] as Extract<EditDocumentOperation, { kind: "set_clip_moves" }>).moves;
  expect(moves.map((move) => [move.frame, move.scale])).toEqual([[59, 1], [68, 1.35]]);
});

test("removing a keyframe sends the rest", () => {
  const moves = [
    { frame: 0, scale: 1, x: 0, y: 0, ease: "linear" as const },
    { frame: 30, scale: 1.2, x: 0, y: 0, ease: "linear" as const },
  ];
  const { operations } = mountEffects(withMain({ moves }));
  fireEvent.click(screen.getByRole("button", { name: "Remove keyframe at 0:01.0" }));
  expect((operations[0] as Extract<EditDocumentOperation, { kind: "set_clip_moves" }>).moves).toEqual([moves[0]!]);
});

test("Add box sends a centred box over the clip's source window", () => {
  const { operations } = mountEffects();
  fireEvent.click(screen.getByRole("button", { name: "Add box" }));
  expect(payload(operations[0]!)).toEqual({
    kind: "set_clip_marks",
    operation_id: "op",
    clip_id: "clip_main",
    marks: [{ kind: "box", x: 0.35, y: 0.35, w: 0.3, h: 0.3, side: "top", from_frame: 0, to_frame: 120, color: "accent" }],
  });
});

test("a mark's end before its start says why and sends nothing", () => {
  const mark = { kind: "box", x: 0.35, y: 0.35, w: 0.3, h: 0.3, side: "top", from_frame: 30, to_frame: 90, color: "accent" };
  const { operations } = mountEffects(withMain({ emphasis: { highlight: false, arrow: false, marks: [mark] } }));
  const until = screen.getByLabelText("Box 1 until");
  fireEvent.change(until, { target: { value: "0:00.5" } });
  fireEvent.blur(until);
  expect(operations).toHaveLength(0);
  expect(screen.getByRole("alert").textContent).toBe("A mark must end after it starts.");
});
