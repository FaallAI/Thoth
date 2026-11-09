/// <reference types="bun-types" />

import { expect, test } from "bun:test";

import type { EditDocumentOperation, EditDocumentV2, EditorAsset } from "@/api/control-plane";

import {
  clipLabelSource,
  formatTimecode,
  rulerTicks,
  MAX_ZOOM,
  MIN_ZOOM,
  applyTimelineOperation,
  fitMarkers,
  framesLeft,
  sourceSpan,
  speedPercent,
  carrySceneClips,
  clampZoom,
  compatibleTrackIds,
  createAddClipFromAssetOperation,
  framesToPixels,
  isTimelineDocument,
  placementChanges,
  issueTarget,
  pixelsToFrames,
  snapCandidates,
  snapFrame,
  timelineIssues,
  visibleLanes,
} from "./timeline_domain";
import { sceneStripDocument } from "./timeline-test-fixtures";

function documentV2(): EditDocumentV2 {
  return {
    schema_version: 2,
    document_id: "edoc_001",
    project_id: "project_001",
    revision: 2,
    template: { template_id: "vertical_text_story", version: 1 },
    canvas: { width: 1080, height: 1920, fps: 30, duration_in_frames: 300 },
    scenes: [
      {
        scene_id: "scene_001",
        start_frame: 0,
        duration_in_frames: 300,
        role: "source",
        clip_ids: ["clip_main"],
      },
    ],
    asset_refs: [
      {
        asset_id: "asset_video",
        project_id: "project_001",
        kind: "video",
        has_audio: true,
        validation_state: "ready",
      },
    ],
    tracks: [
      {
        track_id: "track_main",
        kind: "main_video",
        label: "Main",
        order: 0,
        hidden: false,
        muted: false,
        locked: false,
        clip_ids: ["clip_main"],
      },
      {
        track_id: "track_music",
        kind: "music",
        label: "Music",
        order: 1,
        hidden: false,
        muted: false,
        locked: false,
        clip_ids: ["clip_music"],
      },
      {
        track_id: "track_locked",
        kind: "b_roll",
        label: "Locked B-roll",
        order: 2,
        hidden: false,
        muted: false,
        locked: true,
        clip_ids: [],
      },
    ],
    clips: [
      {
        kind: "video", speed: 1,
        clip_id: "clip_main",
        track_id: "track_main",
        asset_id: "asset_video",
        from_frame: 0,
        duration_in_frames: 300,
        source_from_frame: 0,
        ownership: "ai_managed",
        hidden: false,
        locked: false,
        fit: "cover",
        blur_enabled: false,
        fade_in_frames: 0,
        fade_out_frames: 0,
        motion: "none",
        hold_after_source: false,
        emphasis: { highlight: false, arrow: false },
      },
      {
        kind: "audio", speed: 1,
        clip_id: "clip_music",
        track_id: "track_music",
        asset_id: "asset_video",
        from_frame: 0,
        duration_in_frames: 120,
        source_from_frame: 0,
        ownership: "ai_managed",
        hidden: false,
        locked: false,
        volume: 1,
        fade_in_frames: 0,
        fade_out_frames: 0,
      },
    ],
  };
}

const READY_ASSET: EditorAsset = {
  asset_id: "asset_new",
  project_id: "project_001",
  kind: "video",
  media_type: "video/mp4",
  has_audio: true,
  validation_state: "ready",
};

test("frames convert to pixels and back at the current zoom", () => {
  expect(framesToPixels(90, 2)).toBe(180);
  expect(pixelsToFrames(180, 2)).toBe(90);
  expect(pixelsToFrames(-40, 2)).toBe(0);
  expect(pixelsToFrames(45, 2)).toBe(23);
});

test("zoom stays inside its bounds and ignores unusable values", () => {
  expect(clampZoom(MIN_ZOOM / 10)).toBe(MIN_ZOOM);
  expect(clampZoom(MAX_ZOOM * 10)).toBe(MAX_ZOOM);
  expect(clampZoom(Number.NaN)).toBe(1);
  expect(clampZoom(1.5)).toBe(1.5);
});

test("snap chooses the nearest candidate then the stable lower frame", () => {
  expect(snapFrame(101, [100, 102], 2)).toBe(100);
  expect(snapFrame(104, [100], 2)).toBe(104);
  expect(snapFrame(103, [100, 106], 3)).toBe(100);
  expect(snapFrame(50, [], 4)).toBe(50);
});

test("snap candidates cover clip edges, canvas bounds, and the playhead", () => {
  expect(snapCandidates(documentV2(), { excludeClipId: "clip_main", playhead: 45 })).toEqual([
    0, 45, 120, 300,
  ]);
});

test("only track kinds that accept the clip kind are offered", () => {
  expect(compatibleTrackIds(documentV2(), "video")).toEqual(["track_main"]);
  expect(compatibleTrackIds(documentV2(), "audio")).toEqual(["track_music"]);
  expect(compatibleTrackIds(documentV2(), "caption")).toEqual([]);
});

test("lanes are ordered by track order and carry their clips in frame order", () => {
  const lanes = visibleLanes(documentV2());

  expect(lanes.map((lane) => lane.track.track_id)).toEqual([
    "track_main",
    "track_music",
    "track_locked",
  ]);
  expect(lanes[0].clips.map((clip) => clip.clip_id)).toEqual(["clip_main"]);
  expect(lanes[2].clips).toEqual([]);
});

test("a timeline document is distinguished from a version 1 document", () => {
  expect(isTimelineDocument(documentV2())).toBe(true);
  expect(isTimelineDocument({ schema_version: 1 } as never)).toBe(false);
});

test("a main-track gap and an over-long clip are reported as issues", () => {
  const document = documentV2();
  document.clips![0].from_frame = 30;
  document.clips![0].duration_in_frames = 270;
  document.clips![1].duration_in_frames = 400;

  expect(timelineIssues(document)).toEqual([
    {
      issue_id: "main_track_gap:clip_main",
      code: "main_track_gap",
      target: { kind: "clip", id: "clip_main", track_id: "track_main" },
    },
    {
      issue_id: "clip_exceeds_canvas:clip_music",
      code: "clip_exceeds_canvas",
      target: { kind: "clip", id: "clip_music", track_id: "track_music" },
    },
  ]);
});

test("an overlap on one track is reported once for the later clip", () => {
  const document = documentV2();
  document.clips!.push({ ...document.clips![1], clip_id: "clip_music_b", from_frame: 60 });
  document.tracks[1]!.clip_ids!.push("clip_music_b");

  expect(timelineIssues(document).map((issue) => issue.issue_id)).toEqual([
    "clip_overlap:clip_music_b",
  ]);
});

test("an issue maps to the selection that reveals it", () => {
  expect(
    issueTarget({
      issue_id: "clip_overlap:clip_a",
      code: "clip_overlap",
      target: { kind: "clip", id: "clip_a", track_id: "track_a" },
    }),
  ).toEqual({ selectedTrackId: "track_a", selectedClipId: "clip_a" });
  expect(
    issueTarget({
      issue_id: "track_empty:track_a",
      code: "track_empty",
      target: { kind: "track", id: "track_a", track_id: "track_a" },
    }),
  ).toEqual({ selectedTrackId: "track_a", selectedClipId: "" });
});

test("moving a clip retargets its track without mutating the source document", () => {
  const original = documentV2();
  const moved = applyTimelineOperation(
    original,
    {
      kind: "move_clip",
      operation_id: "op_001",
      clip_id: "clip_music",
      target_track_id: "track_music",
      from_frame: 60,
      ripple: false,
    },
    {},
  );

  expect(moved.clips!.find((clip) => clip.clip_id === "clip_music")!.from_frame).toBe(60);
  expect(original).toEqual(documentV2());
});

test("a ripple move repacks its track from the earliest start", () => {
  const document = documentV2();
  document.clips!.push({ ...document.clips![1], clip_id: "clip_music_b", from_frame: 200 });
  document.tracks[1]!.clip_ids!.push("clip_music_b");

  const rippled = applyTimelineOperation(
    document,
    {
      kind: "move_clip",
      operation_id: "op_001",
      clip_id: "clip_music_b",
      target_track_id: "track_music",
      from_frame: 0,
      ripple: true,
    },
    {},
  );

  expect(
    rippled
      .clips!.filter((clip) => clip.track_id === "track_music")
      .map((clip) => [clip.clip_id, clip.from_frame]),
  ).toEqual([
    ["clip_music", 120],
    ["clip_music_b", 0],
  ]);
});

test("splitting uses the supplied IDs and preserves the source range", () => {
  const split = applyTimelineOperation(
    documentV2(),
    {
      kind: "split_clip",
      operation_id: "op_001",
      clip_id: "clip_main",
      split_frame: 90,
      left_clip_id: "clip_left",
      right_clip_id: "clip_right",
    },
    {},
  );

  expect(
    split
      .clips!.filter((clip) => clip.track_id === "track_main")
      .map((clip) => [clip.clip_id, clip.from_frame, clip.duration_in_frames]),
  ).toEqual([
    ["clip_left", 0, 90],
    ["clip_right", 90, 210],
  ]);
  expect(split.tracks[0].clip_ids).toEqual(["clip_left", "clip_right"]);
});

test("trimming the start advances the source and keeps the end frame", () => {
  const trimmed = applyTimelineOperation(
    documentV2(),
    { kind: "trim_clip_start", operation_id: "op_001", clip_id: "clip_main", from_frame: 40 },
    {},
  );
  const clip = trimmed.clips!.find((entry) => entry.clip_id === "clip_main")!;

  expect([clip.from_frame, clip.duration_in_frames]).toEqual([40, 260]);
  expect((clip as { source_from_frame: number }).source_from_frame).toBe(40);
});

test("a clip added from a ready asset copies only the safe projection", () => {
  const added = applyTimelineOperation(
    documentV2(),
    {
      kind: "add_clip_from_asset",
      operation_id: "op_001",
      track_id: "track_main",
      clip_id: "clip_added",
      asset_id: "asset_new",
      from_frame: 0,
      duration_in_frames: 60,
      source_from_frame: 0,
    },
    { asset_new: READY_ASSET },
  );

  expect(added.asset_refs!.map((asset) => asset.asset_id)).toEqual(["asset_video", "asset_new"]);
  expect(JSON.stringify(added)).not.toContain("media_type");
  expect(added.tracks[0].clip_ids).toEqual(["clip_main", "clip_added"]);
});

test.each([
  [
    "a locked clip",
    { kind: "trim_clip_end", operation_id: "op", clip_id: "clip_locked", end_frame: 10 },
    "clip is locked",
  ],
  [
    "a locked track",
    {
      kind: "move_clip",
      operation_id: "op",
      clip_id: "clip_main",
      target_track_id: "track_locked",
      from_frame: 0,
      ripple: false,
    },
    "track is locked",
  ],
  [
    "an unknown clip",
    { kind: "remove_clip", operation_id: "op", clip_id: "clip_missing" },
    "operation references an unknown clip",
  ],
  [
    "a zero-length trim",
    { kind: "trim_clip_end", operation_id: "op", clip_id: "clip_main", end_frame: 0 },
    "trim must leave a positive duration",
  ],
  [
    "a split at the clip edge",
    {
      kind: "split_clip",
      operation_id: "op",
      clip_id: "clip_main",
      split_frame: 0,
      left_clip_id: "clip_a",
      right_clip_id: "clip_b",
    },
    "split frame must fall inside the clip",
  ],
  [
    "volume on a non-audio clip",
    { kind: "set_clip_volume", operation_id: "op", clip_id: "clip_main", volume: 0.5 },
    "volume applies only to audio clips",
  ],
  [
    "an unavailable asset",
    {
      kind: "add_clip_from_asset",
      operation_id: "op",
      track_id: "track_main",
      clip_id: "clip_added",
      asset_id: "asset_missing",
      from_frame: 0,
      duration_in_frames: 60,
      source_from_frame: 0,
    },
    "operation references an unavailable asset",
  ],
])("%s is refused", (_name, operation, message) => {
  const document = documentV2();
  document.clips!.push({
    ...document.clips![0],
    clip_id: "clip_locked",
    locked: true,
    from_frame: 0,
  });
  document.tracks[0]!.clip_ids!.push("clip_locked");

  expect(() => applyTimelineOperation(document, operation as never, {})).toThrow(message);
});

test("a cross-project asset never enters the document", () => {
  expect(() =>
    applyTimelineOperation(
      documentV2(),
      {
        kind: "add_clip_from_asset",
        operation_id: "op",
        track_id: "track_main",
        clip_id: "clip_added",
        asset_id: "asset_new",
        from_frame: 0,
        duration_in_frames: 60,
        source_from_frame: 0,
      },
      { asset_new: { ...READY_ASSET, project_id: "project_other" } },
    ),
  ).toThrow("asset belongs to another project");
});

test("track settings flip without touching any clip", () => {
  const muted = applyTimelineOperation(
    documentV2(),
    { kind: "set_track_muted", operation_id: "op", track_id: "track_music", muted: true },
    {},
  );

  expect(muted.tracks[1].muted).toBe(true);
  expect(muted.clips).toEqual(documentV2().clips);
});

const IDS = { operationId: "op_asset", clipId: "clip_asset" };
const TIMED_ASSET: EditorAsset = { ...READY_ASSET, duration_in_frames: 600 };

test("an asset becomes an add operation on the first compatible unlocked track", () => {
  expect(createAddClipFromAssetOperation(roomyDocument(), TIMED_ASSET, 145, IDS)).toEqual({
    kind: "add_clip_from_asset",
    operation_id: "op_asset",
    clip_id: "clip_asset",
    track_id: "track_main",
    asset_id: "asset_new",
    from_frame: 145,
    duration_in_frames: 155,
    source_from_frame: 0,
  });

  expect(
    createAddClipFromAssetOperation(
      documentV2(),
      { ...TIMED_ASSET, kind: "audio", media_type: "audio/mpeg" },
      0,
      IDS,
    ),
  ).toMatchObject({ track_id: "track_music", from_frame: 120, duration_in_frames: 180 });
});

test("an image lands on a video track for one canvas second", () => {
  expect(
    createAddClipFromAssetOperation(
      roomyDocument(),
      { ...READY_ASSET, kind: "image", media_type: "image/png" },
      112,
      IDS,
    ),
  ).toMatchObject({ track_id: "track_main", duration_in_frames: 30, from_frame: 112 });
});

test("an asset with no unlocked compatible track produces no operation", () => {
  const document = documentV2();
  const locked = {
    ...document,
    tracks: document.tracks.map((track) => ({ ...track, locked: true })),
  };
  expect(createAddClipFromAssetOperation(locked, READY_ASSET, 0, IDS)).toBeUndefined();

  const withoutAudio = {
    ...document,
    tracks: document.tracks.filter((track) => track.kind !== "music"),
  };
  expect(
    createAddClipFromAssetOperation(
      withoutAudio,
      { ...READY_ASSET, kind: "audio", media_type: "audio/mpeg" },
      0,
      IDS,
    ),
  ).toBeUndefined();
});

function documentWithCaptions(locked = false): EditDocumentV2 {
  const document = documentV2();
  document.tracks.push({
    track_id: "track_caption",
    kind: "caption",
    label: "Captions",
    order: 3,
    hidden: false,
    muted: false,
    locked: false,
    clip_ids: ["clip_caption"],
  });
  document.clips!.push({
    kind: "caption",
    clip_id: "clip_caption",
    track_id: "track_caption",
    from_frame: 0,
    duration_in_frames: 120,
    ownership: "ai_managed",
    hidden: false,
    locked,
    style_slot: "caption_default",
    cues: [
      { from_frame: 0, duration_in_frames: 60, text: "hello" },
      { from_frame: 60, duration_in_frames: 60, text: "world" },
    ],
  });
  return document;
}

const captionText = (clipId: string, cueIndex: number) =>
  ({
    kind: "set_caption_cue_text",
    operation_id: "op_caption_1",
    clip_id: clipId,
    cue_index: cueIndex,
    text: "Corrected caption",
  }) as const;

test("a caption cue edit changes only that cue's text", () => {
  const source = documentWithCaptions();
  const next = applyTimelineOperation(source, captionText("clip_caption", 1), {});

  const expected = structuredClone(source);
  const caption = expected.clips!.at(-1)!;
  if (caption.kind === "caption") caption.cues[1]!.text = "Corrected caption";
  expect(next).toEqual(expected);
  expect(source.clips!.at(-1)).toEqual(documentWithCaptions().clips!.at(-1));
});

test.each([
  ["a non-caption clip", documentWithCaptions(), "clip_main", 0, "caption cue unavailable"],
  ["an out-of-range cue", documentWithCaptions(), "clip_caption", 2, "caption cue unavailable"],
  ["a missing clip", documentWithCaptions(), "clip_missing", 0, "unknown clip"],
  ["a locked caption", documentWithCaptions(true), "clip_caption", 0, "clip is locked"],
] as const)("a caption cue edit on %s is refused", (_label, document, clipId, cueIndex, message) => {
  expect(() => applyTimelineOperation(document, captionText(clipId, cueIndex), {})).toThrow(message);
});

test("lane selection has one implementation, shared with the renderer", async () => {
  const shared = await import("@thoth/remotion-composition");
  expect(visibleLanes).toBe(shared.visibleLanes);
});

const reorder = (sceneId: string, toIndex: number) =>
  ({ kind: "reorder_scene", operation_id: "op_reorder", scene_id: sceneId, to_index: toIndex }) as const;

/** Each scene-bound clip as its scene and its offset inside that scene. */
function sceneMembership(document: EditDocumentV2): Record<string, [string, number]> {
  const starts = new Map(document.scenes.map((scene) => [scene.scene_id, scene.start_frame]));
  return Object.fromEntries(
    (document.clips ?? []).map((clip) => [
      clip.clip_id,
      [clip.scene_id!, clip.from_frame - starts.get(clip.scene_id!)!],
    ]),
  );
}

test.each([
  ["the last scene to the front", "scene_003", 0, ["scene_003", "scene_001", "scene_002"]],
  ["the first scene to the end", "scene_001", 2, ["scene_002", "scene_003", "scene_001"]],
  ["a middle scene to the front", "scene_002", 0, ["scene_002", "scene_001", "scene_003"]],
] as const)("moving %s carries its clips without drift", (_label, sceneId, toIndex, order) => {
  const source = sceneStripDocument();

  const next = applyTimelineOperation(source, reorder(sceneId, toIndex), {});

  expect(next.scenes.map((scene) => scene.scene_id)).toEqual([...order]);
  let frame = 0;
  for (const scene of next.scenes) {
    expect(scene.start_frame).toBe(frame);
    frame += scene.duration_in_frames;
  }
  expect(next.canvas.duration_in_frames).toBe(source.canvas.duration_in_frames);
  expect(sceneMembership(next)).toEqual(sceneMembership(source));
  expect(next.clips!.map((clip) => clip.duration_in_frames)).toEqual(
    source.clips!.map((clip) => clip.duration_in_frames),
  );
});

test.each([
  ["an unknown scene", reorder("scene_missing", 0), "unknown scene"],
  ["an index past the end", reorder("scene_001", 3), "scene index is out of range"],
] as const)("a scene reorder naming %s is refused", (_label, operation, message) => {
  expect(() => applyTimelineOperation(sceneStripDocument(), operation, {})).toThrow(message);
});

test("a scene reorder that would move a locked clip is refused", () => {
  const source = sceneStripDocument();
  source.clips!.find((clip) => clip.clip_id === "clip_still")!.locked = true;

  expect(() => applyTimelineOperation(source, reorder("scene_002", 0), {})).toThrow("clip is locked");
});

test("an asset added to a scene stays bound to that scene", () => {
  const next = applyTimelineOperation(
    documentV2(),
    {
      kind: "add_clip_from_asset",
      operation_id: "op_asset",
      clip_id: "clip_asset",
      track_id: "track_main",
      asset_id: "asset_new",
      from_frame: 0,
      duration_in_frames: 30,
      source_from_frame: 0,
      scene_id: "scene_001",
    },
    { asset_new: READY_ASSET },
  );

  expect(next.clips!.at(-1)!.scene_id).toBe("scene_001");
});

/** The scene strip plus an empty caption lane, as every upgraded draft has. */
function captionReadyStrip(): EditDocumentV2 {
  const document = sceneStripDocument();
  document.tracks.push({
    track_id: "track_caption",
    kind: "caption",
    label: "Captions",
    order: 4,
    hidden: false,
    muted: false,
    locked: false,
    clip_ids: [],
  });
  return document;
}

const addCaption = (overrides: Partial<{ scene_id: string; clip_id: string; track_id: string }> = {}) =>
  ({
    kind: "add_caption_clip",
    operation_id: "op_caption",
    clip_id: "clip_cap",
    track_id: "track_caption",
    scene_id: "scene_002",
    text: "Hello",
    ...overrides,
  }) as const;

const cueTiming = (fromFrame: number, duration: number, cueIndex = 0) =>
  ({
    kind: "set_caption_cue_timing",
    operation_id: "op_timing",
    clip_id: "clip_cap",
    cue_index: cueIndex,
    from_frame: fromFrame,
    duration_in_frames: duration,
  }) as const;

const captionStyle = (clipId: string) =>
  ({ kind: "set_caption_style", operation_id: "op_style", clip_id: clipId, style_slot: "source" }) as const;

const captioned = () => applyTimelineOperation(captionReadyStrip(), addCaption(), {});

test("a text place applies to a text clip and to nothing else", () => {
  const place = (clipId: string) =>
    ({ kind: "set_text_place", operation_id: "op_place", clip_id: clipId, style_slot: "title_top" }) as const;
  const document = captioned();
  const text = document.clips!.find((clip) => clip.kind === "text")!;

  const next = applyTimelineOperation(document, place(text.clip_id), {});

  expect(next.clips!.find((clip) => clip.clip_id === text.clip_id)).toMatchObject({ style_slot: "title_top" });
  expect(() => applyTimelineOperation(document, place("clip_cap"), {})).toThrow("text place applies only to text clips");
});

test("a caption added to a scene spans it with one default cue", () => {
  const next = captioned();

  expect(next.clips!.at(-1)).toEqual({
    kind: "caption",
    clip_id: "clip_cap",
    track_id: "track_caption",
    scene_id: "scene_002",
    from_frame: 30,
    duration_in_frames: 60,
    ownership: "user_edited",
    hidden: false,
    locked: false,
    style_slot: "caption_default",
    cues: [{ from_frame: 0, duration_in_frames: 60, text: "Hello" }],
  });
  expect(next.tracks.find((track) => track.track_id === "track_caption")!.clip_ids).toEqual(["clip_cap"]);
});

test.each([
  ["an unknown scene", addCaption({ scene_id: "scene_missing" }), "unknown scene"],
  ["a reused clip ID", addCaption({ clip_id: "clip_001" }), "reuses an existing clip ID"],
  ["a non-caption track", addCaption({ track_id: "track_music" }), "clip kind is incompatible with track"],
] as const)("a caption naming %s is refused", (_label, operation, message) => {
  expect(() => applyTimelineOperation(captionReadyStrip(), operation, {})).toThrow(message);
});

test("cue timing moves a cue inside its caption and refuses one outside it", () => {
  const next = applyTimelineOperation(captioned(), cueTiming(10, 20), {});
  const caption = next.clips!.at(-1)!;

  expect(caption.kind === "caption" && caption.cues[0]).toEqual({ from_frame: 10, duration_in_frames: 20, text: "Hello" });
  expect(() => applyTimelineOperation(captioned(), cueTiming(50, 20), {})).toThrow(
    "caption cues must stay inside their clip",
  );
  expect(() => applyTimelineOperation(captioned(), cueTiming(0, 10, 1), {})).toThrow("caption cue unavailable");
});

test("a caption style applies only to an unlocked caption", () => {
  const styled = applyTimelineOperation(captioned(), captionStyle("clip_cap"), {});
  expect(styled.clips!.at(-1)).toMatchObject({ style_slot: "source" });

  expect(() => applyTimelineOperation(captioned(), captionStyle("clip_001"), {})).toThrow(
    "caption style applies only to caption clips",
  );
  const locked = captioned();
  locked.clips!.at(-1)!.locked = true;
  expect(() => applyTimelineOperation(locked, captionStyle("clip_cap"), {})).toThrow("clip is locked");
});

test("a scene-bound caption keeps its cues inside the caption when the scene shrinks", () => {
  const document = applyTimelineOperation(captioned(), cueTiming(50, 10), {});
  const previousStarts = new Map(document.scenes.map((scene) => [scene.scene_id, scene.start_frame]));
  document.scenes[1]!.duration_in_frames = 30;
  document.scenes[2]!.start_frame = 60;

  carrySceneClips(document, previousStarts);

  expect(document.clips!.at(-1)).toMatchObject({
    duration_in_frames: 30,
    cues: [{ from_frame: 29, duration_in_frames: 1, text: "Hello" }],
  });
});

/** documentV2 with one timed subtitle region on the main clip. */
function blurredDocument(): EditDocumentV2 {
  const document = documentV2();
  const main = document.clips!.find((clip) => clip.clip_id === "clip_main")!;
  Object.assign(main, {
    blur_regions: [{ x: 0.1, y: 0.65, w: 0.8, h: 0.09, from_frame: 30, to_frame: 90 }],
  });
  return document;
}

test("set_clip_blur toggles blur_enabled", () => {
  const on = applyTimelineOperation(
    blurredDocument(),
    { kind: "set_clip_blur", operation_id: "op_blur", clip_id: "clip_main", blur_enabled: true },
    {},
  );
  const main = on.clips!.find((clip) => clip.clip_id === "clip_main")!;
  expect(main.kind === "video" && main.blur_enabled).toBe(true);
});

test("split keeps blur regions", () => {
  const split = applyTimelineOperation(
    blurredDocument(),
    {
      kind: "split_clip",
      operation_id: "op_001",
      clip_id: "clip_main",
      split_frame: 90,
      left_clip_id: "clip_left",
      right_clip_id: "clip_right",
    },
    {},
  );
  for (const id of ["clip_left", "clip_right"]) {
    const clip = split.clips!.find((candidate) => candidate.clip_id === id)!;
    expect(clip.kind === "video" ? clip.blur_regions : null).toEqual([
      { x: 0.1, y: 0.65, w: 0.8, h: 0.09, from_frame: 30, to_frame: 90 },
    ]);
  }
});

test("a timecode is minutes, seconds and tenths, and never divides by a zero frame rate", () => {
  expect(formatTimecode(0, 30)).toBe("0:00.0");
  expect(formatTimecode(906, 30)).toBe("0:30.2");
  expect(formatTimecode(1440, 30)).toBe("0:48.0");
  expect(formatTimecode(3600 * 30, 30)).toBe("60:00.0");
  expect(formatTimecode(5, 0)).toBe("0:00.0");
});

test("ruler ticks take the smallest step that leaves room for a label", () => {
  // At zoom 1 a second is 30 px, so 5 s (150 px) is the first step of at least 80 px.
  expect(rulerTicks(300, 30, 1)).toEqual([
    { frame: 0, label: "0:00" },
    { frame: 150, label: "0:05" },
    { frame: 300, label: "0:10" },
  ]);
  expect(rulerTicks(90, 30, 4).map((tick) => tick.label)).toEqual(["0:00", "0:01", "0:02", "0:03"]);
  // Zoomed far out, the step stops at a minute.
  expect(rulerTicks(30 * 150, 30, 0.01).map((tick) => tick.frame)).toEqual([0, 1800, 3600]);
});

test("an empty document or a zero frame rate still has one tick", () => {
  expect(rulerTicks(0, 30, 1)).toEqual([{ frame: 0, label: "0:00" }]);
  expect(rulerTicks(300, 0, 1)).toEqual([{ frame: 0, label: "0:00" }]);
});

type AnyClip = NonNullable<EditDocumentV2["clips"]>[number];
const labelled = (extra: Record<string, unknown>) =>
  ({ clip_id: "c", track_id: "t", kind: "video", from_frame: 0, duration_in_frames: 30, ...extra }) as AnyClip;

test("a clip reads as its words, then its role in the story, then its kind", () => {
  const cue = (text: string) => ({ from_frame: 0, duration_in_frames: 30, text });
  expect(clipLabelSource(labelled({ kind: "caption", cues: [cue("Udara pekat"), cue("Next")] }))).toEqual({
    text: "Udara pekat",
  });
  expect(clipLabelSource(labelled({ kind: "text", heading: "Kabut menyelimuti" }))).toEqual({
    text: "Kabut menyelimuti",
  });
  expect(clipLabelSource(labelled({ kind: "overlay", source_role: "comment_card" }))).toEqual({
    role: "comment_card",
  });
  expect(clipLabelSource(labelled({ kind: "audio" }))).toEqual({ kind: "audio" });
});

test("empty words fall through to the role", () => {
  const blank = { from_frame: 0, duration_in_frames: 30, text: "  " };
  expect(
    clipLabelSource(labelled({ kind: "caption", cues: [blank], source_role: "hook" })),
  ).toEqual({ role: "hook" });
  expect(clipLabelSource(labelled({ kind: "text", heading: "", source_role: "outro" }))).toEqual({
    role: "outro",
  });
});

// Found by the write audit: the server refuses a clip past the canvas or over a main-track clip.
function roomyDocument(): EditDocumentV2 {
  const document = documentV2();
  document.clips![0]!.duration_in_frames = 100;
  document.scenes[0]!.duration_in_frames = 100;
  return document;
}

test("write-audit: a long asset is cut to the room the canvas leaves", () => {
  expect(createAddClipFromAssetOperation(roomyDocument(), TIMED_ASSET, 200, IDS)).toMatchObject({
    track_id: "track_main",
    from_frame: 200,
    duration_in_frames: 100,
  });
});

test("write-audit: an asset dropped on a clip lands right after it", () => {
  expect(createAddClipFromAssetOperation(roomyDocument(), TIMED_ASSET, 40, IDS)).toMatchObject({
    track_id: "track_main",
    from_frame: 100,
    duration_in_frames: 200,
  });
});

test("write-audit: an asset stops where the next clip starts", () => {
  const document = roomyDocument();
  document.clips![0]!.from_frame = 150;
  expect(createAddClipFromAssetOperation(document, TIMED_ASSET, 30, IDS)).toMatchObject({
    from_frame: 30,
    duration_in_frames: 120,
  });
});

test("write-audit: a full track passes the asset to the next one that takes it", () => {
  const document = documentV2();
  document.tracks[2]!.locked = false;
  expect(createAddClipFromAssetOperation(document, TIMED_ASSET, 45, IDS)).toMatchObject({
    track_id: "track_locked",
    from_frame: 45,
    duration_in_frames: 255,
  });
});

test("write-audit: no room on any track produces no operation", () => {
  expect(createAddClipFromAssetOperation(documentV2(), TIMED_ASSET, 45, IDS)).toBeUndefined();
});

test("write-audit: a placement reports what it changed and nothing else", () => {
  const add = (document: EditDocumentV2, playhead: number) =>
    createAddClipFromAssetOperation(document, TIMED_ASSET, playhead, IDS)!;
  const roomy = roomyDocument();
  expect(placementChanges(roomy, TIMED_ASSET, 200, add(roomy, 200))).toEqual({
    cut: true,
    later: false,
    otherTrack: false,
  });
  expect(placementChanges(roomy, TIMED_ASSET, 40, add(roomy, 40))).toMatchObject({ later: true, otherTrack: false });

  const full = documentV2();
  full.tracks[2]!.locked = false;
  expect(placementChanges(full, TIMED_ASSET, 45, add(full, 45))).toMatchObject({ later: false, otherTrack: true });

  const short = { ...TIMED_ASSET, duration_in_frames: 20 };
  const whole = createAddClipFromAssetOperation(roomy, short, 200, IDS)!;
  expect(placementChanges(roomy, short, 200, whole)).toEqual({ cut: false, later: false, otherTrack: false });
});

test("write-audit: every placed clip is one the document accepts without an issue", () => {
  const document = roomyDocument();
  for (const playhead of [0, 40, 99, 100, 200, 299]) {
    const operation = createAddClipFromAssetOperation(document, TIMED_ASSET, playhead, IDS)!;
    const placed = applyTimelineOperation(document, operation, { asset_new: TIMED_ASSET });
    const codes = timelineIssues(placed).map((issue) => issue.code);
    expect(codes).not.toContain("clip_exceeds_canvas");
    expect(codes).not.toContain("clip_overlap");
  }
});

// Spec 2026-11-08 §5.1: time typed as time, and tracks named in plain language.
import { messages } from "@/lib/i18n";
import { parseTimecode, trackName } from "./timeline_domain";
import { timelineDocument as fixtureDocument } from "./timeline-test-fixtures";

test("parseTimecode reads m:ss.f, seconds and m:ss, and nothing else", () => {
  expect(parseTimecode("0:07.5", 30)).toBe(225);
  expect(parseTimecode("7.5", 30)).toBe(225);
  expect(parseTimecode("1:02", 30)).toBe(1860);
  expect(parseTimecode(" 0:01.0 ", 30)).toBe(30);
  expect(parseTimecode("abc", 30)).toBeNull();
  expect(parseTimecode("", 30)).toBeNull();
  expect(parseTimecode("-1", 30)).toBeNull();
});

test("trackName names a track by its kind, in the reader's language, numbering a second one", () => {
  const doc = fixtureDocument();
  const en = (key: string) => (messages.en as Record<string, string>)[key]!;
  const id = (key: string) => (messages.id as Record<string, string>)[key]!;
  const main = doc.tracks.find((track) => track.track_id === "track_main")!;
  expect(trackName(en as never, doc, main)).toBe("Main video");
  expect(trackName(id as never, doc, main)).toBe("Video utama");
  const second = { ...doc.tracks.find((track) => track.track_id === "track_broll")!, track_id: "track_broll_2", order: 9, label: "B-Roll 2" };
  doc.tracks.push(second);
  expect(trackName(en as never, doc, second)).toBe("B-roll 2");
});

// Tier 2 (spec 2026-11-08 §6): the mirror of the server's duplicate, fit, crop and fade operations.
const tier2Op = (operation: Record<string, unknown>) =>
  ({ operation_id: `op_${String(operation.kind)}`, ...operation }) as EditDocumentOperation;
const applied = (document: EditDocumentV2, ...operations: Record<string, unknown>[]) =>
  operations.reduce<EditDocumentV2>((current, operation) => applyTimelineOperation(current, tier2Op(operation), {}), document);
const clipIn = (document: EditDocumentV2, clipId: string) =>
  document.clips!.find((clip) => clip.clip_id === clipId)! as Record<string, unknown>;

test("duplicate_clip copies under a new id", () => {
  const result = applied(fixtureDocument(), {
    kind: "duplicate_clip",
    clip_id: "clip_main",
    new_clip_id: "clip_copy",
    track_id: "track_main",
    from_frame: 150,
  });
  const original = clipIn(result, "clip_main");
  const copy = clipIn(result, "clip_copy");
  for (const field of ["asset_id", "ownership", "fit", "position", "blur_regions"]) {
    expect(copy[field]).toEqual(original[field]);
  }
  expect(copy.scene_id ?? null).toBeNull();
  expect([copy.from_frame, copy.duration_in_frames]).toEqual([150, 120]);
  expect(result.tracks.find((track) => track.track_id === "track_main")!.clip_ids).toContain("clip_copy");
});

test("a duplicate drops its Story role", () => {
  // Operator, 2026-11-09: a copy is footage, not a second Hook.
  const document = fixtureDocument();
  const hook = { ...document, clips: document.clips!.map((clip) => (clip.clip_id === "clip_main" ? { ...clip, source_role: "hook" as const } : clip)) };
  const result = applied(hook, { kind: "duplicate_clip", clip_id: "clip_main", new_clip_id: "clip_copy", track_id: "track_main", from_frame: 150 });
  expect(clipIn(result, "clip_copy").source_role ?? null).toBeNull();
  expect(clipIn(result, "clip_main").source_role).toBe("hook");
});

test("duplicate_clip refuses a reused id, a locked track and an incompatible track", () => {
  const dup = (new_clip_id: string, track_id: string) => ({
    kind: "duplicate_clip",
    clip_id: "clip_main",
    new_clip_id,
    track_id,
    from_frame: 150,
  });
  expect(() => applied(fixtureDocument(), dup("clip_music", "track_broll"))).toThrow("reuses an existing clip ID");
  expect(() =>
    applied(fixtureDocument(), { kind: "set_track_locked", track_id: "track_broll", locked: true }, dup("clip_copy", "track_broll")),
  ).toThrow("track is locked");
  expect(() => applied(fixtureDocument(), dup("clip_copy", "track_music"))).toThrow("incompatible");
});

test("set_clip_fit, set_clip_crop and set_clip_fades set their fields", () => {
  const crop = { left: 0.1, top: 0, width: 0.8, height: 1 };
  const result = applied(
    fixtureDocument(),
    { kind: "set_clip_fit", clip_id: "clip_main", fit: "contain" },
    { kind: "set_clip_crop", clip_id: "clip_main", crop },
    { kind: "set_clip_fades", clip_id: "clip_main", fade_in_frames: 15, fade_out_frames: 30 },
  );
  const main = clipIn(result, "clip_main");
  expect([main.fit, main.crop, main.fade_in_frames, main.fade_out_frames]).toEqual(["contain", crop, 15, 30]);
  expect(clipIn(applied(result, { kind: "set_clip_crop", clip_id: "clip_main", crop: null }), "clip_main").crop).toBeNull();
  const music = applied(fixtureDocument(), { kind: "set_clip_fades", clip_id: "clip_music", fade_in_frames: 10, fade_out_frames: 20 });
  expect(clipIn(music, "clip_music").fade_out_frames).toBe(20);
  expect(() => applied(fixtureDocument(), { kind: "set_clip_fit", clip_id: "clip_music", fit: "fill" })).toThrow();
});

test("fades longer than the clip are refused", () => {
  expect(() =>
    applied(fixtureDocument(), { kind: "set_clip_fades", clip_id: "clip_main", fade_in_frames: 100, fade_out_frames: 100 }),
  ).toThrow("fades must stay inside their clip");
});

test("trim and split shrink fades to fit", () => {
  const faded = applied(fixtureDocument(), { kind: "set_clip_fades", clip_id: "clip_main", fade_in_frames: 40, fade_out_frames: 40 });
  const trimmed = clipIn(applied(faded, { kind: "trim_clip_end", clip_id: "clip_main", end_frame: 60 }), "clip_main");
  expect(trimmed.fade_in_frames).toBe(40);
  expect(Number(trimmed.fade_in_frames) + Number(trimmed.fade_out_frames)).toBeLessThanOrEqual(60);
  const split = applied(faded, {
    kind: "split_clip",
    clip_id: "clip_main",
    split_frame: 50,
    left_clip_id: "clip_left",
    right_clip_id: "clip_right",
  });
  expect(clipIn(split, "clip_left").fade_out_frames).toBe(0);
  expect(clipIn(split, "clip_right").fade_in_frames).toBe(0);
});

test("add_text_clip works without a story role", () => {
  const result = applied(
    fixtureDocument(),
    { kind: "add_track", track_id: "track_overlay", track_kind: "overlay", label: "Overlay", order: 9 },
    {
      kind: "add_text_clip",
      clip_id: "clip_pasted",
      track_id: "track_overlay",
      from_frame: 0,
      duration_in_frames: 90,
      heading: "Hello",
      body: "",
      style_slot: "title",
    },
  );
  expect(clipIn(result, "clip_pasted").source_role ?? null).toBeNull();
});

test("an asset dropped on a lane goes on that track at that frame, or nowhere", () => {
  const doc = fixtureDocument();
  const video = { asset_id: "asset_video", project_id: doc.project_id, kind: "video", media_type: "video/mp4", has_audio: true, validation_state: "ready", duration_in_frames: 30 } as EditorAsset;
  const ids = { operationId: "op_drop", clipId: "clip_drop" };
  expect(createAddClipFromAssetOperation(doc, video, 0, ids, { trackId: "track_broll", frame: 10 })).toMatchObject({
    track_id: "track_broll",
    from_frame: 10,
    duration_in_frames: 30,
  });
  expect(createAddClipFromAssetOperation(doc, video, 0, ids, { trackId: "track_broll", frame: 160 })).toBeUndefined();
  expect(createAddClipFromAssetOperation(doc, video, 0, ids, { trackId: "track_music", frame: 10 })).toBeUndefined();
});

// Tier 3a (spec 2026-11-08 section 7): speed keeps a clip's place and changes its source span,
// with the same whole-percent maths as the server.
test("speed maths matches the server's integers", () => {
  const clip = { duration_in_frames: 31, speed: 1.5, source_from_frame: 10 } as const;
  expect(speedPercent(clip)).toBe(150);
  expect(speedPercent({})).toBe(100);
  expect(sourceSpan(clip)).toBe(47); // ceil(31 * 1.5)
  expect(framesLeft(clip, { duration_in_frames: 100 })).toBe(60); // floor(90 / 1.5)
});

test("set_clip_speed sets the speed and keeps the clip's place", () => {
  const before = clipIn(fixtureDocument(), "clip_main");
  const result = applied(fixtureDocument(), { kind: "set_clip_speed", clip_id: "clip_main", speed: 2 });
  const main = clipIn(result, "clip_main");
  expect([main.speed, main.ownership]).toEqual([2, "user_edited"]);
  expect([main.from_frame, main.duration_in_frames]).toEqual([before.from_frame, before.duration_in_frames]);
});

test("set_clip_speed refuses a text clip", () => {
  const doc = fixtureDocument();
  doc.clips!.push({ kind: "text", clip_id: "clip_t", track_id: "track_main", from_frame: 0, duration_in_frames: 10, ownership: "user_edited", hidden: false, locked: false, heading: "Hi", body: "", style_slot: "title" } as never);
  expect(() => applied(doc, { kind: "set_clip_speed", clip_id: "clip_t", speed: 2 })).toThrow("speed applies only to video and audio clips");
});

test("a trim start on a 2x clip moves its source twice as far", () => {
  const fast = applied(fixtureDocument(), { kind: "set_clip_speed", clip_id: "clip_main", speed: 2 });
  const result = applied(fast, { kind: "trim_clip_start", clip_id: "clip_main", from_frame: 10 });
  expect(clipIn(result, "clip_main").source_from_frame).toBe(20);
});

test("a split of a 1.5x clip starts the right part at the left span", () => {
  const fast = applied(fixtureDocument(), { kind: "set_clip_speed", clip_id: "clip_main", speed: 1.5 });
  const result = applied(fast, { kind: "split_clip", clip_id: "clip_main", split_frame: 31, left_clip_id: "clip_l", right_clip_id: "clip_r" });
  expect(clipIn(result, "clip_r").source_from_frame).toBe(46);
  expect([clipIn(result, "clip_l").speed, clipIn(result, "clip_r").speed]).toEqual([1.5, 1.5]);
});

test("slip_clip moves only the source", () => {
  const before = clipIn(fixtureDocument(), "clip_main");
  const main = clipIn(applied(fixtureDocument(), { kind: "slip_clip", clip_id: "clip_main", source_from_frame: 40 }), "clip_main");
  expect([main.source_from_frame, main.ownership]).toEqual([40, "user_edited"]);
  expect([main.from_frame, main.duration_in_frames]).toEqual([before.from_frame, before.duration_in_frames]);
});

test("slip_clip refuses an image", () => {
  const doc = fixtureDocument();
  Object.assign(doc.asset_refs![0]!, { kind: "image" });
  expect(() => applied(doc, { kind: "slip_clip", clip_id: "clip_main", source_from_frame: 4 })).toThrow("an image has no source time");
});

// Tier 3a: markers on the ruler, mirrored from the server.
test("add_marker, set_marker and remove_marker", () => {
  const added = applied(fixtureDocument(), { kind: "add_marker", marker_id: "marker_1", frame: 30, label: "" });
  expect(added.markers).toEqual([{ marker_id: "marker_1", frame: 30, label: "" }]);
  const named = applied(added, { kind: "set_marker", marker_id: "marker_1", frame: 45, label: "Hook ends" });
  expect(named.markers).toEqual([{ marker_id: "marker_1", frame: 45, label: "Hook ends" }]);
  expect(applied(named, { kind: "remove_marker", marker_id: "marker_1" }).markers).toEqual([]);
});

test("marker operations refuse a reused id and an unknown marker", () => {
  const added = applied(fixtureDocument(), { kind: "add_marker", marker_id: "marker_1", frame: 30, label: "" });
  expect(() => applied(added, { kind: "add_marker", marker_id: "marker_1", frame: 40, label: "" })).toThrow("operation reuses an existing marker ID");
  expect(() => applied(added, { kind: "remove_marker", marker_id: "marker_x" })).toThrow("operation references an unknown marker");
});

test("fitMarkers moves a marker past the end onto the last frame", () => {
  const doc = fixtureDocument();
  doc.markers = [
    { marker_id: "inside", frame: 10, label: "" },
    { marker_id: "late", frame: doc.canvas.duration_in_frames + 40, label: "" },
  ];
  fitMarkers(doc);
  expect(doc.markers.map((marker) => marker.frame)).toEqual([10, doc.canvas.duration_in_frames - 1]);
});

// Final review 2026-11-09, Important 3: a held clip still starts inside its media.
test("slip_clip refuses a held clip that would start past its media", () => {
  const doc = fixtureDocument();
  Object.assign(doc.asset_refs![0]!, { duration_in_frames: 400 });
  Object.assign(doc.clips!.find((clip) => clip.clip_id === "clip_main")!, { hold_after_source: true });
  expect(() => applied(doc, { kind: "slip_clip", clip_id: "clip_main", source_from_frame: 400 })).toThrow("a held clip must start inside its source");
});
