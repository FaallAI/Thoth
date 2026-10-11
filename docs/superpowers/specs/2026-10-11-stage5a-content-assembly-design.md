# Stage 5a: Content Assembly Core in Python — Design

Status: written spec approved by the operator on 2026-10-11; implemented on branch
`feat/stage5a-content-assembly` (see `docs/superpowers/plans/2026-10-11-stage5a-content-assembly.md`).

## 1. Goal

Produce a validated, typed Content Set for an acquired post without Scout: the main entry with
its final renderer OCR (`trim_start`, `mute_audio`, `subtitle_blur`), the audience comments with
their real card crops, and the figures the post is about. The Content Set is a versioned,
checksummed workflow artifact.

Roadmap Stage 5 ("Move Content Assembly") is split (operator, 2026-10-11):

- **5a (this spec):** main and its final OCR, multi-source comments, figures, validation, and
  the Content Set artifact.
- **5b:** footage (object extraction, keyword search across platforms, relevance, spam, and
  reaction gates, footage OCR, crops and downloads).
- Later: forced-main packaging (`scout/main_footage/`).

## 2. Scope

In scope:

- Port of Scout's subtitle classifier (`classifyOcrFrames`, `buildSampleTimes` in
  `scout/lib/subtitle_vision.ts`) and its frame-coverage rule, fed by local RapidOCR boxes.
- Port of the comment merge (`dedupeAndRankComments` and the sticker and link-spam filters in
  `scout/lib/comment_engine.ts`) over comments Python acquisition already collects.
- Port of the figures prompt (`scout/pipeline/extract_figures.ts`) through OpenRouter.
- Port of the content-set lint rules that apply to 5a (`scout/lib/validate.ts`) as Pydantic
  validators.
- A new `assemble_content` activity and an `assembly` stage in `SourceInvestigationWorkflow`.

Out of scope, recorded as follow-ups (section 12): footage, forced main, moving the Content
Set page and the Studio import onto this artifact, a converter to the legacy Scout format, and
an OCR verdict cache.

## 3. Decisions (operator, 2026-10-11)

1. Stage 5 is split into 5a (this spec) and 5b (footage); forced main comes later.
2. Output is a workflow artifact only. The dashboard Content Set page and Studio import keep
   reading the Rust route `/api/scout/content-set/data` until a later sub-stage moves them.
3. The artifact uses a new typed schema (`ContentSet` v1). Field names follow Scout where they
   mean the same thing; media are artifact locations with checksums, never absolute paths;
   there are no free-form `[k: string]: any` fields.
4. Assembly runs automatically after attribution in the same workflow. Comments and figures may
   fail without failing the stage. The final main OCR and validation are required: when they
   fail, the workflow fails with `content_assembly_failed` and no partial Content Set is
   written.
5. OCR engine: the Scout classifier ported unchanged, fed by local RapidOCR (approach 1). No
   DeepSeek-OCR, no Novita (its key is dead since 2026-10-09).
6. A required tool that is missing is an explicit error, never a skip or a silent degradation
   (operator: "ffmpeg harus ada jika tidak ada langsung buat error, jangan di buat seolah olah
   aman"). This also applies to tests: the two ffmpeg tests of Stage 4 lose their `skipif`.
   The operator installs ffmpeg in WSL for local runs.

## 4. Architecture

A new package `thoth_control_plane/assembly/`, shaped like `attribution/` (service, ports,
adapters):

```python
content_set = await ContentAssembler(ports).build(inputs)
```

| Unit | Responsibility | Depends on |
|---|---|---|
| `models.py` | `ContentSet` v1 and its parts (section 6). Validators make inconsistent OCR directives, a video without OCR, and a non-video without an image unrepresentable. | — |
| `subtitles.py` | Pure port of `classifyOcrFrames` and `buildSampleTimes`. Input: frames of boxes (`x0`, `y0`, `x1`, `y1`, `text`, all normalized 0..1). Output: `outcome`, `trim_start`, `mute_audio`, `subtitle_blur`. | — |
| `comments.py` | Pure merge: dedupe, filter, rank, cap. | — |
| `figures.py` | Prompt, response schema, and parsing for figures. | `FigureModel` port |
| `ocr.py` | Main OCR analysis: sample times, frame extraction with recovery, RapidOCR, coverage rule, classification. | `FrameSampler`, `TextReader` ports |
| `service.py` | `ContentAssembler`: chooses the main, runs OCR, comments, and figures, builds and validates the Content Set. | ports |
| `ports.py` | `FrameSampler`, `TextReader` (shared with attribution), `FigureModel`, `DurationProbe`. | — |
| adapters | `FfmpegFrameSource.frames_at(video, times, width)`, `FfprobeDuration`, `RapidOcrReader` (adds `left` and `right`), `AgnoFigureModel`. | ffmpeg, ffprobe, RapidOCR, OpenRouter |
| `activities/content_assembly.py` | `assemble_content`: reads the reports and the attribution, runs the assembler, writes the artifact. | assembler |

`TextBox` in `attribution/matching.py` gains `left` and `right` (fractions of the frame
width); RapidOCR's quads already carry x. Attribution ignores the new fields.

### Temporal integration

- Setting `THOTH_CONTENT_ASSEMBLY_ENABLED` (default `false`) reaches the workflow input as
  `assemble_content`, exactly as `THOTH_SOURCE_ATTRIBUTION_ENABLED` reaches `attribute_source`
  through `temporal_gateway.py`. With the flag off, behavior is unchanged.
- In the `identify_original` branch the stage `assembly` runs after attribution. It also runs
  when attribution is off, failed, or unresolved; the main is then the input post. A legacy
  Scout report (no v3 report) skips assembly, as it skips attribution.
- Activity options: `start_to_close_timeout` 10 minutes, `heartbeat_timeout` 2 minutes driven
  by a background heartbeat task (as in `attribute_source`), `RetryPolicy(maximum_attempts=2)`.
- A cancel request during assembly cancels the activity and ends the workflow `CANCELLED`.
- The activity raises a non-retryable application error with the reason code when assembly
  fails; the workflow records `WorkflowFailure(code="content_assembly_failed",
  failed_stage="assembly", retryable=True)` and the reason in its event payload.
- Temporal history carries only IDs, the OCR outcome, comment and figure counts, the reason
  code, and elapsed milliseconds. Never comment text, paths, or model output.

## 5. Flow

### A1 Inputs

- `reports/<workflow_id>/source-report.json` (schema 3): required; missing or invalid fails
  with `source_report_missing`.
- `reports/<workflow_id>/source-attribution.json`: optional.
- When the verdict is `replaced`, the original's report at the location the attribution
  activity wrote: required; missing fails with `original_report_missing`.

### A2 Main selection

- Verdict `replaced`: main is the original (`main.source = "original"`).
- Otherwise (`original`, `unresolved`, no attribution): main is the input post
  (`main.source = "input"`).

Main fields: `url` (canonical), `platform`, `title` (first 120 characters of the post text),
`description` (post text), `owner_handle`, `published_at`, `engagement`, `profile_card`.

Main media, by what the report holds:

- A video: `kind = "video"`, `video` is the media reference, and `ocr` is required (A3).
- Images only: `kind = "images"`, `images` holds every image in order, no OCR.
- Neither, with a post card: `kind = "card"`, `card` is the post card.
- Neither and no post card: fails with `main_media_missing`.

Media references reuse the location and checksum already in the report; nothing is copied.

### A3 Final OCR (required for a video main)

1. Tools: ffmpeg and ffprobe must be executable. Worker startup checks them when
   `THOTH_CONTENT_ASSEMBLY_ENABLED` is true and refuses to start with `ffmpeg_missing` or
   `ffprobe_missing`. If one disappears later, the activity fails with the same code, never a
   media failure code.
2. Duration: `duration_seconds` from the report; when absent, ffprobe. No duration fails with
   `duration_probe_failed`.
3. Sample times: `build_sample_times(duration, THOTH_SUBTITLE_OCR_MAX_FRAMES)` (intro samples
   at 0.5, 1, 2, 3, 4, 5 s, the rest spread to the end, at most 12 by default).
4. Frames: ffmpeg seeks each time and writes one JPEG at **720 px** wide (attribution uses 360;
   subtitle glyphs need more; RapidOCR's detector resizes the short side to 736 anyway), JPEG
   quality `-q:v 2`. One ffmpeg process per sample time: a single multi-input process and a
   `select` filter were no faster (bench, 2026-10-11: 1.48 s, 1.48 s, 1.35 s for 12 frames of
   a 90 s 1080x1920 clip), and per-time calls keep the recovery simple. A failed extraction
   retries at offsets +0, +0.25, +0.5, +1 s, two attempts each, as Scout does.
5. Boxes: RapidOCR reads each frame with the angle classifier off (`use_cls=False`: video
   text is upright; bench: 549 ms instead of 841 ms per 720 px frame, identical text); boxes
   are normalized to 0..1 on both axes. The image ships the PP-OCRv6 small models (rapidocr
   3.9.2 default), whose single recognizer covers 46 Latin-script languages, Indonesian
   included.
6. Coverage: valid frames must equal requested frames, else `incomplete_frame_coverage`. Only
   complete coverage may produce a verdict.
7. Classification: `classify_ocr_frames(frames, duration)`.

### A4 Comments

- Sources, in order: the main's report, then the input report when the main is the original
  (the repost's discussion is about the same story).
- Filter: empty text, sticker-only (`[Sticker]`, `[Stiker]`), and link-first text.
- Dedupe key: lowercased author, `|`, first 60 characters of the trimmed, lowercased text.
- Rank by likes descending (stable), cap at 12.
- Each comment keeps its real card (location and checksum) or none. Never a synthetic card.
- A malformed comment is dropped, not fatal. No comments is valid.

### A5 Figures

- Input: main title and description, as Scout's pipeline passes them, plus the cover
  headline that attribution's vision read already recorded (`cover_vision` evidence
  `headline: ...`) when there is one. Figures never wait for the OCR, so the call runs
  concurrently with A3 and costs no wall time. 5b adds footage descriptions, as Scout does.
- One structured call through Agno over OpenRouter (`THOTH_FIGURES_MODEL`, default the pinned
  `deepseek/deepseek-v4-flash-0731`, the successor of Scout's `deepseek-v3.1`, with native
  structured outputs), prompt ported from `extract_figures.ts` (rules unchanged, translated to
  English).
- Output: at most 5 figures, each `name`, `type` (`person`, `organization`, `community`),
  `role`, `description`; `figures_status = "ok"`.
- An empty list from the model: `figures_status = "none"`.
- No key, a timeout, a provider error, or an unparseable answer: `figures = []`,
  `figures_status = "unavailable"`, one warning log with enums only.

### A6 Build, validate, write

- Build `ContentSet` v1; Pydantic validation is the lint. A validation error fails with
  `content_set_invalid`.
- Write `reports/<workflow_id>/content-set.json` atomically (`.part`, then `os.replace`).
- Artifact: `ArtifactRef(artifact_id="art_content_set_<sha256[:20]>", kind="content_set",
  media_type="application/json", checksum="sha256:<hex>")`, served by the existing
  `/workflows/{workflow_id}/artifacts/{artifact_id}` route.
- Idempotency: a retry rebuilds the whole document and replaces the file atomically; nothing
  is appended, so comments and figures can never be duplicated.
- `ponytail:` no per-sub-step artifacts; local OCR on 12 frames takes seconds, so a retry
  recomputes it. Cache the verdict per media checksum if retries become costly (section 12).

## 6. Output contract: `ContentSet` v1

```text
ContentSet
  schema_version: 1
  workflow_id
  attribution_verdict: original | replaced | unresolved | none
  main: Main
  comments: list[Comment]            max 12
  figures: list[Figure]              max 5
  figures_status: ok | none | unavailable
  footage: list                      always empty in 5a (max_length 0); 5b defines its items

Main
  source: input | original
  url, platform, title, description, owner_handle, published_at?, engagement
  kind: video | images | card
  video: MediaRef?                   exactly when kind = video
  images: list[MediaRef]             non-empty exactly when kind = images
  card: MediaRef?                    exactly when kind = card
  profile_card: MediaRef?
  ocr: MainOcr?                      exactly when kind = video

MediaRef
  location (safe relative), media_type, checksum, bytes, width?, height?, duration_seconds?

MainOcr
  schema_version: 1
  engine: rapidocr
  analyzer_version: "subtitle-classifier-v1"
  analyzed_at
  requested_frames, valid_frames    valid_frames = requested_frames > 0
  outcome: clean | cover | subtitle
  trim_start >= 0
  mute_audio
  subtitle_blur: list[BlurRegion]

BlurRegion
  x, y >= 0; w, h > 0; x + w <= 1; y + h <= 1
  start, end: both present or both absent; 0 <= start <= end

Comment
  text, author, likes >= 0, source: input | original, card: MediaRef?

Figure
  name, type: person | organization | community, role, description
```

Consistency validators, from `validate.ts`:

- `clean`: `trim_start == 0`, `mute_audio` false, no blur regions.
- `cover`: `trim_start > 0`, `mute_audio` false, no blur regions.
- `subtitle`: `mute_audio` true, at least one blur region (`trim_start` may be positive: the
  hybrid case).

The artifact holds public post URLs, handles, bounded text, counts, and relative locations.
Never a CDN URL, a cookie, a proxy, a prompt, or raw model output.

## 7. Configuration and degradation

| Variable | Default | When missing |
|---|---|---|
| `THOTH_CONTENT_ASSEMBLY_ENABLED` | `false` | no `assembly` stage |
| `THOTH_SUBTITLE_OCR_MAX_FRAMES` | `12` | default |
| `THOTH_FIGURES_MODEL` | `deepseek/deepseek-v4-flash-0731` (dated, never a `~latest` alias) | default |
| `THOTH_OPENROUTER_API_KEY` (exists) | — | `figures_status = "unavailable"` |
| `THOTH_FFMPEG` (exists), ffprobe beside it | — | worker refuses to start (`ffmpeg_missing`, `ffprobe_missing`) |

No new secret. Non-secret variables go in the compose environment; if the stage 1 preflight
rejects them, its allowlist is updated in the plan.

Failure codes of the stage: `source_report_missing`, `original_report_missing`,
`main_media_missing`, `ffmpeg_missing`, `ffprobe_missing`, `duration_probe_failed`,
`incomplete_frame_coverage`, `content_set_invalid`, `artifact_write_failed`.

## 8. Security and history hygiene

- Activity inputs and results carry IDs, enums, counts, and an `ArtifactRef`; never text.
- Logs carry enums and counts only.
- The figures prompt sends public post text only; the model answer is validated and bounded
  before it is stored.

## 9. Testing

All offline; no live test joins the suite.

1. **Classifier parity:** the ~20 `classifyOcrFrames` cases of
   `scout/lib/subtitle_vision.test.ts` (CJK captions, phantom OCR, hybrid cover and subtitle,
   partial failure, real geometry, lower-third, left captions, stable two-line, watermark,
   banner jitter, real cover, separate and simultaneous tracks, split transition, two-line,
   repeated text) ported with identical inputs and expected outputs, plus the
   `buildSampleTimes` cases.
2. **Units:** comment merge (dedupe, sticker, link spam, ranking, cap, real cards only);
   `ContentSet` validators (each inconsistent OCR state, video without OCR, images empty,
   card missing, footage non-empty); main selection per verdict and without attribution;
   figures parsing and the three statuses.
3. **OCR analysis with fake ports:** frame recovery offsets, incomplete coverage, duration from
   the report and from the probe, missing ffmpeg and ffprobe codes kept apart from media
   failures.
4. **Activity and workflow:** atomic write and matching checksum; a retry replaces, never
   duplicates; OCR failure ends `FAILED` with `content_assembly_failed`; comment or figure
   failure still succeeds; flag off keeps today's behavior; cancel during assembly; history
   free of text; worker startup refuses to run without ffmpeg when the flag is on.
5. **Adapters:** `frames_at` against an ffmpeg `testsrc` clip and `FfprobeDuration`, which
   fail (not skip) without ffmpeg; RapidOCR returns `left` and `right`. The two existing
   Stage 4 ffmpeg tests drop their `skipif`.
6. **RapidOCR calibration goldens**, recorded once live with separate operator authorization:
   four to six real videos (intro headline, speech subtitles, news lower-third, clean, hybrid).
   Each fixture stores the per-frame RapidOCR boxes (no video) and the verdict the operator
   confirms; the suite replays them offline. If a classifier threshold must move for RapidOCR
   geometry, the change is recorded as an amendment to this spec with its evidence.

## 10. Departures from Scout

- RapidOCR line boxes replace DeepSeek-OCR grounding blocks; the classifier is unchanged.
- `ocr_model` becomes `engine` plus `analyzer_version`; there is no provider model to go stale.
- Comments come from reports acquisition already wrote; no browser visit during assembly.
- Media are artifact references with checksums, not absolute `image_path` values.
- The lint is a set of model validators; an invalid Content Set cannot be written.
- Figures also read the cover headline attribution recorded; Scout passed only title and
  description.
- Expected OCR cost for a video main: about 8 s on the worker (12 frames at roughly 0.12 s
  extraction and 0.55 s recognition each), with figures running alongside.

## 11. Operator gates

Each needs its own authorization: push, deploy, and the live recording of the calibration
goldens. The live smoke joins the final acceptance (ADR 0001).

## 12. Follow-ups

- 5b: footage.
- Forced main (`scout/main_footage/`).
- The Content Set page and Studio import read this artifact; then the Rust route retires.
- A converter to the legacy Scout format, only if a consumer still needs it.
- An OCR verdict cache keyed by media checksum.
