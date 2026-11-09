# Studio Timeline Tier 3b Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Clips show what they hold, and audio has a draggable volume line:
- a filmstrip on video and image clips;
- a waveform on audio clips;
- a volume line on audio clips that can be dragged.

**Architecture:**
- **One small "glance" per asset.** A video or image gets a filmstrip (one JPEG of frames side by side). An audio asset gets its peaks.
- **Built lazily.** The glance is built the first time a browser asks for it. ffmpeg reads the asset through the media store's existing `probe_source`.
- **Cached beside the asset.** It is kept in the media store under `glance/`, which the upload sweep never touches, and served by one authenticated GET.
- **Read by the dashboard.** The dashboard fetches each asset's glance once, the way Story fetches previews. The Timeline draws the window of the source that each clip plays, at its speed.
- **The volume line** is the existing `set_clip_volume` operation, dragged or keyed.

**Tech Stack:** Python 3.12 (FastAPI, pydantic 2.14, ffmpeg in the image), React 19 + TypeScript (Bun, happy-dom), tester-army/e2e 0.21.

**Spec:** `docs/superpowers/specs/2026-11-08-studio-timeline-track-design.md` §7 (first bullet), and §4 decision 6: Tier 3b is its own plan and PR.

Branch `feat/studio-timeline-tier3b` from master `d3c89bbb`.

## Global Constraints

- **Read media safely.**
  - Every ffmpeg call reads a local path or a signed store URL, with the protocol whitelist `media_probe.py` already uses (`URL_PROTOCOLS` or `FILE_PROTOCOLS`), and a timeout.
  - A missing ffmpeg is an explicit error code, never a silent skip (operator rule: required tools fail loud).
- **Degrade gracefully** (AGENTS.md). With no glance (missing ffmpeg, a failed build, an older server, or a read error), a clip draws exactly as it does today.
- **No document field, no migration, no paid call.** A rollback to Tier 3a images is safe: the files under `glance/` are simply unused.
- **The glance GET follows the normal project auth.** As a GET, it is open to a read-scope token. It carries small derived pictures and numbers, not the media itself.
- **One user action is one patch.** A volume drag previews while moving and commits one `set_clip_volume` on release.
- **Strings and commits.** Dashboard strings come in English and Indonesian. Each commit is one `git commit -m` subject of at most 72 characters, with no body, no trailer and no AI attribution.
- **e2e** tests are deterministic. Write tests run only in the throwaway project with a one-day write token.

## Decisions taken in this plan (the builder's calls, §8; listed for the operator)

- **Lazy, not on upload.** Uploads and Studio imports stay as fast as today, and existing assets need no backfill job. The first look at a long video waits a few seconds; after that the glance comes from the cache.
- **Sizes.**
  - **Filmstrip:**
    - at most 60 frames, one every `ceil(duration / 60)` seconds and at least one second apart;
    - 72 px tall, as one JPEG;
    - an image asset gets one frame.
  - **Peaks:**
    - at most 2000 values, one per `max(0.1, duration / 2000)` seconds;
    - each value is the loudest sample in its stretch, from 0 to 100, against full scale (not normalised), so a quiet track looks quiet.
- **What gets what.**
  - Video and image assets get a filmstrip.
  - Audio assets get peaks, and that includes narration voices, music and SFX.
  - A video's own sound gets no waveform here (YAGNI).
- **The volume line is a level, not a curve.** Keyframes stay a non-goal (spec §2).
  - The line spans the clip at the clip's `volume`, from 0 at the bottom to 1 at the top. That matches the Inspector slider.
  - It is a `role="slider"`: drag it, or use the arrow keys (±0.05). Home and End go to 0 and 1.
  - It is hidden when the Timeline is view-only or the clip is locked.
- **Failures are not cached.** A failed build answers 503 with a code and is tried again next time. A built glance is cached for good, because an asset's bytes never change.

## Review Focus

1. **A sped-up, slipped, split or trimmed clip** shows the part of the strip and the peaks that it actually plays. Test: Task 5 (`glanceWindow`).
2. **A missing ffmpeg, a corrupt file, a timeout or a store outage.** The endpoint answers 503 with a code, and the clip draws as before. No crash, and no cached failure. Tests: Tasks 3 and 4.
3. **An asset of another project, or one that is not ready**, gets a 404, never a glance. Test: Task 3.
4. **A very long asset** (a 10-minute music bed) stays within the size limits. Test: Task 1.
5. **A volume drag.** Releasing outside the clip, or pressing Escape, commits nothing extra or cancels. A locked clip has no line. Test: Task 6.

---

### Task 1: Glance maths and model

**Files:**
- Create: `python/src/thoth_control_plane/domain/asset_glance.py`
- Test: `python/tests/domain/test_asset_glance.py`

**Interfaces:**
- **Produces, constants:** `STRIP_HEIGHT = 72`, `MAX_STRIP_FRAMES = 60`, `MAX_PEAKS = 2000`, `MIN_PEAK_SECONDS = 0.1`, `PEAK_SAMPLE_RATE = 8000`.
- **Produces, plans:**
  - `def strip_plan(duration_seconds: float) -> tuple[int, int]`, which returns `(frames, seconds_per_frame)`;
  - `def peak_seconds(duration_seconds: float) -> float`.
- **Produces, peaks:** `def peaks_from_pcm(pcm: bytes, sample_rate: int, seconds_per_peak: float) -> list[int]`. It takes signed 16-bit little-endian mono samples and returns, for each stretch, `round(100 * max(abs) / 32768)`, with a last partial stretch included.
- **Produces, the model** (`StrictModel`):
  - `GlanceStrip(image: str  # "data:image/jpeg;base64,…", frame_width: PositiveInt, frame_height: PositiveInt, frames: PositiveInt (≤60), seconds_per_frame: PositiveInt)`;
  - `GlancePeaks(seconds_per_peak: float (gt 0), values: list[Annotated[int, Field(ge=0, le=100)]] (max 2000))`;
  - `AssetGlance(asset_id: OpaqueId, strip: GlanceStrip | None = None, peaks: GlancePeaks | None = None)`.

- [ ] **Step 1: Write the failing tests.**
  - `test_strip_plan_spaces_frames_a_second_apart_up_to_sixty`: `strip_plan(10) == (10, 1)`, `strip_plan(80) == (40, 2)`, `strip_plan(600) == (60, 10)`, `strip_plan(0.4) == (1, 1)`.
  - `test_peak_seconds_has_a_floor_and_a_ceiling_on_count`: `peak_seconds(80) == 0.1`, and `peak_seconds(600) == 0.3`.
  - `test_peaks_from_pcm_take_the_loudest_sample_of_each_stretch`: 8000 Hz, 0.1 s stretches (800 samples). A silent first stretch and a second at ±16384 give `[0, 50]`. A trailing partial stretch counts.
  - `test_a_ten_minute_track_stays_inside_the_limits`: `len(peaks_from_pcm(b"\0\0" * 8000 * 600, 8000, peak_seconds(600))) <= 2000`.
  - `test_a_glance_refuses_more_than_sixty_frames_or_out_of_range_peaks`.
- [ ] **Step 2: Run them.** `make test T=tests/domain/test_asset_glance.py`. Expected: FAIL (module missing).
- [ ] **Step 3: Implement.** Use stdlib `array("h")` for the samples. Use no numpy.
- [ ] **Step 4: Run them again.** Expected: PASS. Then `make lint`.
- [ ] **Step 5: Commit** "Add the asset glance model and its strip and peak maths".

### Task 2: Build a glance with ffmpeg

**Files:**
- Create: `python/src/thoth_control_plane/infrastructure/asset_glance_builder.py`
- Test: `python/tests/infrastructure/test_asset_glance_builder.py`

**Interfaces:**
- **Consumes:** Task 1.
- **Produces, errors:**
  - `class GlanceToolMissing(Exception)`, for when ffmpeg cannot start;
  - `class GlanceBuildFailed(Exception)`, for a non-zero exit, a timeout or empty output.
- **Produces, the builder:** `async def build_glance(ffmpeg: str, source: str, asset: EditorAsset) -> AssetGlance`.
  - **Video:** `-vf fps=1/{s},scale=-2:72,tile={n}x1 -frames:v 1 -q:v 5`.
  - **Image:** `-vf scale=-2:72 -frames:v 1`.
  - **Both:** a JPEG on stdout (`-f image2pipe -vcodec mjpeg -`), with its frame width read from the JPEG's SOF0 or SOF2 marker. Use no Pillow: the API extra may lack it.
  - **Audio:** `-vn -ac 1 -ar 8000 -f s16le -` on stdout, turned into peaks.
  - **Every call:** `-v error`, `-protocol_whitelist` chosen as in `media_probe.probe_media`, stdin `DEVNULL`, and a timeout of `GLANCE_TIMEOUT_SECONDS = 60`.
- **Produces:** `def jpeg_size(data: bytes) -> tuple[int, int]`.

- [ ] **Step 1: Write the failing tests.**
  - `test_jpeg_size_reads_the_frame_header`, on a tiny JPEG made by ffmpeg in the test.
  - `test_a_video_glance_is_a_strip_of_frames_72_px_tall`. The test makes a 3 s 160×90 `testsrc` video with ffmpeg, then expects 3 frames, `frame_height == 72`, and an image starting with `data:image/jpeg;base64,`.
  - `test_an_audio_glance_is_its_peaks`. A 1 s sine wave at full scale gives 10 values that are all at least 90.
  - `test_a_corrupt_file_fails_the_build`: `GlanceBuildFailed`.
  - `test_a_missing_ffmpeg_says_so`: an `ffmpeg="/nonexistent/ffmpeg"` raises `GlanceToolMissing`.

  Mark the tests that need ffmpeg `skipif(shutil.which("ffmpeg") is None)`. The missing-tool test needs nothing.
- [ ] **Step 2: Run them.** `make test T=tests/infrastructure/test_asset_glance_builder.py`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run them again.** Expected: PASS. Then `make lint`.
- [ ] **Step 5: Commit** "Build an asset glance with ffmpeg".

### Task 3: Serve and cache the glance

**Files:**
- Modify: `python/src/thoth_control_plane/application/editor_assets.py` (service method)
- Modify: `python/src/thoth_control_plane/api/routes/editor_assets.py` (GET route)
- Regenerate: `python/openapi.json` and the dashboard types (`bun run generate:control-plane-types`)
- Test:
  - `python/tests/application/test_editor_asset_glance.py`
  - the route tests beside the existing editor-asset route tests

**Interfaces:**
- **Consumes:** Tasks 1 and 2, `MediaStore.probe_source`, `fetch`, `stat` and `put_file`, and `EditorAssetService.get_ready_record`.
- **Produces, storage:**
  - `def glance_location(project_id: str, asset_id: str) -> str`, which gives `glance/{project_id}/{asset_id}.v1.json`;
  - the glance is read from and written to the media store through a temporary file.
- **Produces, the service:** `EditorAssetService.glance(project_id, asset_id) -> AssetGlance`.
  - It returns the cache on a hit.
  - Otherwise it builds the glance under a process-wide `asyncio.Semaphore(2)`, stores it, and returns it.
  - Errors: `EditorAssetNotFound` (404), `GlanceUnavailable(code)` with code `ffmpeg_unavailable`, `glance_failed` or `media_store_unavailable` (503).
- **Produces, the route:** `GET /api/v1/projects/{project_id}/editor-assets/{asset_id}/glance`, with `response_model=AssetGlance` and the header `Cache-Control: private, max-age=86400`.

- [ ] **Step 1: Write the failing tests.**
  - **Service** (fake media store, fake builder):
    - a cache miss builds once and stores at `glance_location`;
    - a second call reads the cache and does not build;
    - a failed build is not stored, and raises `glance_failed`;
    - a missing tool raises `ffmpeg_unavailable`.
  - **Route:**
    - 200 with the glance for a ready asset;
    - 404 for another project's asset and for an unknown one;
    - 503 `{"detail": {"code": "ffmpeg_unavailable"}}`;
    - a read-scope token gets 200.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement, then regenerate the contracts.**
- [ ] **Step 4: Run them again.** Expected: PASS. Then `make test` (full) and `make lint`.
- [ ] **Step 5: Commit** "Serve and cache an asset's glance".

### Task 4: Load the glances in Studio

**Files:**
- Modify: `dashboard/src/api/control-plane.ts` (`getEditorAssetGlance`)
- Modify: `dashboard/src/features/studio/GuidedStudio.tsx`
- Modify: `dashboard/src/features/studio/Timeline.tsx` and `TimelineTrack.tsx` (prop plumbing)
- Test: `GuidedStudio.test.tsx`, `Timeline.test.tsx`

**Interfaces:**
- **Produces:**
  - `ControlPlaneClient.getEditorAssetGlance(projectId: string, assetId: string): Promise<AssetGlance>`;
  - the props `glanceOf?: (assetId: string) => AssetGlance | undefined` on `Timeline`, `TimelineTrack` and `TimelineClip`.
- **GuidedStudio** keeps `glances: Record<string, AssetGlance | null>`. In Timeline mode it asks once for each asset in `asset_refs`, as the Story preview effect does. A refusal stores `null` and is not retried this session. Without the client method, nothing is asked.

- [ ] **Step 1: Write the failing tests.**
  - In Timeline mode, Studio asks `getEditorAssetGlance` once for each asset of the draft, and not again after a re-render.
  - A rejected glance leaves the clip as it was.
  - A client without the method asks nothing.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run them again.** Expected: PASS.
- [ ] **Step 5: Commit** "Load each asset's glance once in Timeline mode".

### Task 5: Filmstrips and waveforms on clips

**Files:**
- Create: `dashboard/src/features/studio/clip_glance.ts`
- Modify: `TimelineClip.tsx`
- Test: `clip_glance.test.ts`, the `TimelineClip` and `Timeline` tests

**Interfaces:**
- **Consumes:** Task 4, and `speedPercent` and `sourceSpan` from `timeline_domain.ts`.
- **Produces:**
  - `export function glanceWindow(clip: { source_from_frame?: number; duration_in_frames: number; speed?: number }, fps: number): { fromSeconds: number; seconds: number }`. This is the stretch of source the clip plays, at its speed.
  - `export function stripStyle(strip: GlanceStrip, window, clipWidthPx: number): CSSProperties`. It sets `backgroundImage`, `backgroundSize` and `backgroundPosition`, so the frame under each point of the clip is the source frame at that moment. The strip's own width is `frames * frame_width`, scaled to the clip.
  - `export function peakSlice(peaks: GlancePeaks, window): number[]`. These are the values inside the window. The waveform draws them as one SVG path (`data-testid="clip-waveform"`, `aria-hidden`).
- **TimelineClip** draws the filmstrip (`data-testid="clip-filmstrip"`) under the label on video and image clips, and the waveform on audio clips. Without a glance it draws as today.

- [ ] **Step 1: Write the failing tests.**
  - `glanceWindow` for a 1× clip at source 30 (30 fps), 60 frames long: `{ fromSeconds: 1, seconds: 2 }`. At 2× it is `{ fromSeconds: 1, seconds: 4 }`.
  - `stripStyle` puts the frame for source second 1 at the clip's left edge, when the strip has 1 s frames.
  - `peakSlice` returns the slice for a slipped clip, and stops at the end of the peaks.
  - **Rendering:**
    - a video clip with a glance shows `clip-filmstrip`, with a background image;
    - an audio clip shows `clip-waveform`;
    - with no glance, neither shows;
    - a text clip never shows them.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run them again.** Expected: PASS. Then `dash_full.sh full`.
- [ ] **Step 5: Commit** "Draw filmstrips and waveforms on clips".

### Task 6: The volume line on audio clips

**Files:**
- Modify: `TimelineClip.tsx`
- Modify: `Timeline.tsx` (preview, commit and cancel)
- Modify: `i18n.ts`
- Test: the `TimelineClip` and `Timeline` tests

**Interfaces:**
- **Consumes:** the existing `set_clip_volume`, and the reducer's `preview_timeline_operation`, `commit_timeline_operation` and `cancel_timeline_preview`.
- **Produces:**
  - the `TimelineClip` prop `onVolume?: (volume: number, phase: "preview" | "commit" | "cancel") => void`;
  - the line: `role="slider"`, `aria-label` "Volume of {clip}", `aria-valuemin` 0, `aria-valuemax` 100, and `aria-valuenow` as the volume in percent.

- [ ] **Step 1: Write the failing tests.**
  - **Drag:** dragging the line on an audio clip previews `set_clip_volume`. Releasing commits once, at the volume under the pointer: top 1, bottom 0, rounded to 0.05.
  - **Keys:**
    - ArrowUp commits +0.05;
    - Home commits 0;
    - End commits 1.
  - **Cancel:** Escape during a drag cancels, and nothing commits.
  - **Hidden** on a locked clip, in a view-only Timeline, and on video clips.
  - **Rest:** the line rests at `volume`. With `volume` 1.6 (the API allows up to 2), it rests at the top.
  - **Strings:**
    - en "Volume of {clip}";
    - id "Volume {clip}".
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.** Pointer handling follows the Timeline's existing gestures: a window move and up, with Escape cancelling.
- [ ] **Step 4: Run them again.** Expected: PASS. Then `dash_full.sh full`.
- [ ] **Step 5: Commit** "Drag an audio clip's volume line".

### Task 7: e2e

**Files:**
- Modify: `e2e/tests-write/timeline-audit.e2e.ts`
- Modify: `e2e/tests/studio-shell-v2.e2e.ts` (read-only)

- [ ] **Step 1: Write the write tests.**
  - `glance: a video clip shows its filmstrip`: `clip-filmstrip` is visible on the Main video clip.
  - `volume: dragging the line to the middle saves about half`:
    - the "Upload · Audio" asset goes on Music;
    - the line is dragged to the clip's vertical middle;
    - the saved `volume` is 0.5 ± 0.05.
- [ ] **Step 2: Write the read-only test.** At 1440, the narrated draft's Main video clip shows `clip-filmstrip`, and a Narration clip shows `clip-waveform`. Both are allowed under the read scope.
- [ ] **Step 3: Run the read-only test against the current stage1.** Expected: FAIL. This is the red step, since the endpoint does not exist yet.
- [ ] **Step 4: Commit** "Add Tier 3b e2e tests".

### Task 8: Records and the final review

**Files:**
- Modify: `CHANGELOG.md` (a new top entry)
- Modify: `docs/ROADMAP.md` (a status line)
- Modify: the SDD ledger

- [ ] **Step 1: Run the full verification.**
  - `make test`;
  - `make lint`;
  - `dash_full.sh full`;
  - `cd renderer && bun test`;
  - the read-only e2e at w1440.
- [ ] **Step 2: Run the final whole-branch review** (executing-plans) with the Review Focus above. Fix Critical and Important findings test-first.
- [ ] **Step 3: Write the CHANGELOG entry.**
  - **Merge and deploy record:**
    - PR #124 merged as `d3c89bbb`;
    - stage1 redeployed to `573b2c92`, with thoth `0532d2f35864`, renderer `966483561d53` and web `4b1e7890a3e6`, and the rollback copy `pins-d723cf15.env`.
  - **What 3b adds, and the builder's decisions above.**
  - **Rollback:** no document field and no migration.
  - **Verification, deferred minors, and the carried Tier 2 and 3a minors.**
  - **Next steps:**
    - the operator gates (token, push and PR, deploy, write e2e, try, merge);
    - then the operator chooses the next track from the roadmap.
- [ ] **Step 4: Commit** "Record Studio Timeline Tier 3b".
