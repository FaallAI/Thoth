# Stage 4 addition: reactions that count as originals — design

Date: 2026-10-13. Status: approved in conversation by the operator (sections 1 and 2, the
required-tool rule, and the open-source tool choices); this document awaits the operator's
review of the written text.

Research: `docs/research/2026-10-13-reaction-as-original-research.md`. Builds on the Stage 4
spec `docs/superpowers/specs/2026-10-08-stage4-source-attribution-design.md` (referred to below
as "the Stage 4 spec") and the Stage 5a spec with its 2026-10-12 amendment.

## 1. Goal

Attribution today treats every reaction or commentary post as a repost and looks for the video
it shows. The operator's rule (2026-10-11) is narrower: a reaction that raises a new viewpoint
or a new issue, and that people discuss, is an original in its own context. After this change
`SourceAttribution` answers `original` for such a reaction, and for any reaction to a text or
image post (there is no video to find). Every other reaction keeps today's path: find the video
it shows, or end `unresolved`.

Success means:

1. The seven golden cases of section 10 replay offline to the operator-confirmed verdicts.
2. Every existing Stage 4 golden that is not a reaction keeps its verdict.
3. A missing required tool, key, or model stops the worker at start, and a vision or Jev call
   that still fails after its retry fails the workflow with an explicit code.

## 2. Operator decisions

| Date | Decision |
|---|---|
| 2026-10-11 | A reaction that raises a new viewpoint or issue and gets people talking is an original; one that only discusses the post is a repost whose source must be found. |
| 2026-10-13 | Research option 3: reaction shape plus a contribution judge fed by a local speech transcript. |
| 2026-10-13 | A reaction to a text or image post is an original. |
| 2026-10-13 | "Gets people talking" needs both: comments discuss the creator's take, and engagement is above the account's usual. Either one unmeasurable means not shown. |
| 2026-10-13 | An original reaction keeps its opening in Stage 5a (no trim). |
| 2026-10-13 | Jev is required: unavailable means an error, never a fallback. Vision is required too, for all of Stage 4, and the rules-only path without a key is removed. |
| 2026-10-13 | A vision or Jev failure at run time fails the workflow (`source_attribution_failed`). |
| 2026-10-13 | Tools: ffmpeg scene detection for frame choice, sherpa-onnx speaker diarization, faster-whisper with large-v3-turbo int8. Deferred: YuNet, sentence embeddings, Qwen3-ASR, audio fingerprints. |

## 3. Scope

In scope:

- Vision frame choice by scene cuts, and three new fields in the cover reading.
- A reaction step in `SourceAttributor.identify`, before the credit search.
- Local transcription (faster-whisper) and speaker diarization (sherpa-onnx).
- A Jev assessment call (contribution scale, comment discussion).
- An engagement baseline from the owner's own profile discovery.
- Required-tool checks at worker start, and typed run-time failures that fail the workflow.
- Recapture of every Stage 4 golden with the new fields, plus the new cases of section 10.
- The Stage 5a OCR goldens of the reactions that become `original`.

Out of scope:

- Persisting the transcript as an artifact (Stage 5b or narration will ask for it).
- Using the reaction's subject as footage (Stage 5b).
- Cross-platform story search for "other accounts repost this reaction" (Stage 8).
- The deferred tools of section 2.

## 4. Flow

```
S1 evidence (as today: 1 fps frames, credit OCR on the first 3 s)
 + scene cuts (ffmpeg) → up to 6 vision frames: 0 s, 1 s, then the middle of the longest shots
 + one vision call → today's cover fields + reaction_shape, subject_media, per-frame `shows`

reaction_shape == none                → S2..S6 exactly as today
subject_media in (text, image)        → verdict original, evidence kind "reaction"
otherwise (video or unknown)          → assessment:
    transcript (faster-whisper) + speaker turns (sherpa-onnx)
    → creator speech and subject speech, split by speaker
    Jev: contribution (score) + comments_discuss_creator (noul)
    engagement ratio from the owner's profile discovery
    original  ⇔ contribution ≥ new_viewpoint  AND  discussion  AND  engagement
    original  → verdict original, evidence kind "reaction"
    otherwise → S2..S6 exactly as today (find the video it shows)
```

The assessment runs once per post and only for reaction-shaped posts. A verdict `original` from
this step ends attribution: the subject is not searched or acquired. The subject handle, when the
evidence holds one, is cited in the evidence for Stage 5b.

## 5. Components

### 5.1 Vision frames and reading

- `attribution/scenes.py` (new): `scene_cuts(video) -> list[float]` runs ffmpeg once with
  `select='gt(scene,THRESHOLD)'` and `showinfo`, and parses the cut times.
  `vision_frames(frames, cuts, duration) -> list[Frame]` picks from the 1 fps frames S1 already
  holds: the frames at 0 s and 1 s (the cover and the credit), then the middle frame of the
  longest shots, in time order, up to 6 frames. Shots shorter than 1 s merge into their
  neighbour. A failed scene pass is a tool error (section 7).
- The vision adapter's frame limit for the cover call becomes 6; the finalist classification
  keeps 3.
- `CoverReading` gains:
  - `reaction_shape: Literal["none", "screenshot", "picture_in_picture", "green_screen",
    "split_screen", "clip_then_talk"]`, default `none`;
  - `subject_media: Literal["video", "text", "image", "none", "unknown"]`, default `none`;
  - `shows: list[Literal["creator", "subject", "both", "other"]]`, one entry per frame sent,
    in order; a list of the wrong length is treated as unknown labels.
- The cover prompt asks for these fields in plain terms (a creator talking to the camera, a
  screenshot of another post, another video shown inside this one). The model describes; the
  code decides.

### 5.2 Transcript and speakers

- Port `Transcriber.transcribe(video) -> Transcript`, where `Transcript` holds segments
  `(start, end, text)` and the language. Adapter `WhisperTranscriber`:
  - faster-whisper on CPU, `compute_type="int8"`;
  - model large-v3-turbo, loaded from `THOTH_WHISPER_MODEL_DIR` with `local_files_only`;
  - `vad_filter=True`;
  - only the first `transcript_seconds` (tuning, starting at 180 s);
  - run in a thread, one transcription at a time per worker, the model loaded once.
  - A video without an audio stream yields an empty transcript; that is valid.
- Port `Diarizer.turns(video) -> list[Turn]` with `(start, end, speaker)`. Adapter
  `SherpaDiarizer`: sherpa-onnx offline speaker diarization with the pyannote 3.0 segmentation
  model and a speaker-embedding model, both ONNX, loaded from `THOTH_DIARIZATION_MODEL_DIR`,
  with fast clustering. It covers the same span as the transcript.
- `attribution/reaction.py` (pure):
  - `split_speech(transcript, turns, shots) -> Speech(creator, subject)`. Each segment takes
    the speaker of its largest overlap. The creator is the speaker with the most speech inside
    frames labelled `creator` or `both`. When no frame shows the creator (a voice-over), the
    creator is the speaker with the most speech overall. All other speakers are subject speech.
  - `engagement_ratio(post, videos) -> float | None`: the post's `play` count over the median
    `play` of the owner's other discovered videos. When the post or fewer than 3 baseline
    videos carry `play`, `like` is used the same way. `None` when neither metric is available.
  - `judge(assessment, ratio, tuning) -> ReactionCall` with the verdict, `original` or
    `repost`, and a reason code.

### 5.3 Jev assessment

- `DecisionModel` gains `assess(state) -> Assessment | None`, answered by the existing
  `JevDecisionModel` in one call with two questions:
  - `contribution`, a `score` question with ordered levels `replay`, `summary`, `opinion`,
    `new_viewpoint`, `new_issue`. The value used is the probability of `new_viewpoint` or
    `new_issue`.
  - `comments_discuss_creator`, a `noul` question. It is asked only when the post has comments;
    without comments, discussion is not shown.
- State: the caption, the credit-scan frame text, the cover headline and scene,
  `reaction_shape`, creator speech, subject speech (each clipped to 6,000 characters), and up
  to 12 comment texts. Jev's context window is 32,000 tokens.

### 5.4 Engagement baseline

- One extra call to the existing `Discoverer` for the post's own platform and owner handle,
  the same profile discovery Stage 4 uses for credited accounts. A discovery failure, an
  unsupported platform, or too few videos makes the ratio `None`, so engagement is not shown.
  This is external content, not a tool error.

### 5.5 Decision rule

```
original ⇔ P(contribution ≥ new_viewpoint) ≥ contribution_threshold
         ∧ comments exist ∧ P(comments_discuss_creator) ≥ discussion_threshold
         ∧ ratio is not None ∧ ratio ≥ engagement_threshold
```

The tuning starts at 0.5, 0.5, and 1.0 and is calibrated on the goldens of section 10. The
calibrated values are recorded in the plan.

### 5.6 Output contract

- `EvidenceKind` gains `reaction`. A reaction step always adds one evidence item whatever its
  outcome, for example `reaction: picture_in_picture, subject video, contribution 0.81,
  discussion 0.74, engagement 2.3x`, or `reaction to a text post`. The detail stays at most 300
  characters and holds no transcript text.
- `SourceAttribution` keeps schema version 1. Only the evidence kind literal widens.
- No new reason codes in the artifact. A reaction judged a repost ends with today's reasons
  (`no_credit`, `no_match`, and the rest), and its `reaction` evidence says why it was not an
  original.

## 6. Stage 5a interaction

No code change. Stage 5a trims only when the attribution verdict is `unresolved` or `none`,
so an original reaction keeps its opening. Two Stage 5a OCR goldens become originals:
`instagram_deHz54GT4ea` and `instagram_deO6A2MSoAt`. Their fixtures get
`trim_allowed: false` and the verdict that replay produces (`clean`, trim 0), once the
Stage 4 goldens confirm `original`.

## 7. Required tools and failures

This replaces the degradation rules in section 7 of the Stage 4 spec for vision and Jev.

### At worker start

With `THOTH_SOURCE_ATTRIBUTION_ENABLED=true`, the worker refuses to start on the first of:

| Code | Condition |
|---|---|
| `openrouter_key_missing` | no OpenRouter key: vision and Jev both use it |
| `ffmpeg_missing`, `ffprobe_missing` | binary not found |
| `rapidocr_missing`, `opencv_missing` | module not importable |
| `whisper_missing` | `faster_whisper` not importable |
| `whisper_model_missing` | `THOTH_WHISPER_MODEL_DIR` lacks the model files |
| `diarization_missing` | `sherpa_onnx` not importable |
| `diarization_model_missing` | `THOTH_DIARIZATION_MODEL_DIR` lacks either ONNX model |

### At run time

- `AttributionPorts.vision` and `.decisions` become required. The rules-only branch of
  `_credit` (no model) is removed, together with its tests.
- A port that cannot do its job raises `AttributionError(code)`. `identify` lets it out
  instead of degrading:

  | Code | Cause |
  |---|---|
  | `vision_unavailable` | a vision read, still failing after the adapter's own retry |
  | `decision_unavailable` | a Jev call, decision or assessment, still failing after retry |
  | `scene_detection_failed` | the ffmpeg scene pass failed |
  | `transcription_failed` | the audio could not be decoded or transcribed |
  | `diarization_failed` | the diarization run failed |
  | tool and model codes | the same codes as at worker start, should a file vanish |

- `attribute_source` returns a typed failure carrying the code, in the same pattern as
  `assemble_content`. The workflow then fails with `WorkflowFailure(code=
  "source_attribution_failed", failed_stage="attribution", retryable=True)`, and the code goes
  into the stage event.
- Unchanged: failures about external content still end `unresolved` with today's reason codes
  and never fail the workflow. These are discovery, candidate acquisition, candidate frames,
  the engagement baseline, and a missing repost report. Any other unexpected exception keeps
  today's `unresolved` handling as well.

## 8. Configuration, image, and security

| Variable | Default |
|---|---|
| `THOTH_WHISPER_MODEL_DIR` | `/opt/thoth/models/whisper-large-v3-turbo` |
| `THOTH_DIARIZATION_MODEL_DIR` | `/opt/thoth/models/diarization` |

- `faster-whisper` and `sherpa-onnx` join the `acquisition` extra. sherpa-onnx runs on the
  onnxruntime RapidOCR already uses.
- The Dockerfile downloads the models at build time from pinned revisions and checks their
  SHA-256, then checks the imports and the model files the way it checks ffmpeg. The image
  grows by about 1 GB, mostly the turbo model. The worker never downloads a model at run time.
- Temporal history keeps carrying only IDs, verdicts, counts, and reason codes. Transcripts,
  comments, and model answers stay inside the activity. Evidence details never quote speech.
- The secret-leak tests extend to the new adapters: no key in logs, events, or artifacts.

## 9. Performance

- Vision: one call per post, with 6 frames instead of 3.
- Reaction-shaped posts with a video subject only:
  - one transcription of at most 180 s of audio, about 90–180 s on CPU if turbo int8 runs at
    1–2× realtime (to be measured, section 10);
  - one diarization pass;
  - one Jev call;
  - one profile discovery.
- The attribution activity keeps its 15-minute timeout and 2-minute heartbeat. Transcription
  heartbeats while it runs.

## 10. Testing

### Unit tests (offline, fakes)

- `scenes.py`: cut parsing from recorded `showinfo` output, merging short shots, choosing
  frames.
- `reaction.py`:
  - speech split, including the voice-over case and the case with one speaker;
  - the engagement ratio's `play`, `like`, and `None` paths;
  - each conjunct of the decision rule failing alone.
- `service.py`:
  - a non-reaction post takes today's path unchanged;
  - a text subject gives `original`;
  - a video subject gives `original`, or goes on to `replaced` or `unresolved`;
  - no comments, or an unknown baseline, means repost;
  - each run-time failure code raises out of `identify`.
- Activity and workflow: a typed failure becomes `source_attribution_failed` with the code in
  the stage event; the external-content failures still end `unresolved`.
- Worker start: each code of section 7 raises.

### Adapter tests

- Whisper and diarization on a silent clip made by ffmpeg: an empty transcript and no turns.
- A missing model directory raises the model code.
- The scene pass on a clip with two colour shots finds the cut.
- Jev assessment with a mocked HTTP response, including the score answer shape.
- Rule (operator, 2026-10-11): a missing tool fails the test. Nothing is skipped.

### Golden cases (live capture, offline replay)

The capture records the vision answers, transcript, turns, Jev answers, and owner discovery,
so replay is offline. Every existing Stage 4 golden is recaptured, because the vision frames
and fields change.

| Case | Kind | Expected | Note |
|---|---|---|---|
| tiktok ZSbEKefJp | repost reaction | `replaced` → x NaraSenyap 2109917400854634989 | new |
| tiktok ZSbEKFuP7 | repost reaction | `replaced` → x gretaamelia7 2109671629206990893 | new |
| tiktok ZSbEKVVra | repost reaction | `replaced` → tiktok ZSbEKps8X | new |
| instagram DeWlWJmyKxP | original reaction | `original` | subject tiktok @koranjakarta, deleted; new |
| instagram DeOUJ60SHeI | original reaction | `original` | was `replaced` → DeMU05JpXCY |
| instagram DeHz54GT4ea | original reaction | `original` | was `replaced` → @manicsofficials |
| instagram DeO6A2MSoAt | reaction to a text post | `original` | was `unresolved` |
| existing non-reaction goldens | as recorded | unchanged | recaptured, `reaction_shape` must come back `none` |

The same capture measures faster-whisper and sherpa-onnx (whisper turbo) speed on CPU on the
reaction videos, and checks the diarization split by hand. If faster-whisper turbo runs slower
than 1× realtime, the plan compares `medium` and the operator chooses.

## 11. Operator gates

Each gate needs its own authorization:

1. Live capture of the goldens and the speed measurement.
2. Push.
3. Merge.
4. Deploy. The image rebuild carries the models, and the worker needs the OpenRouter key, which
   it already holds.

## 12. Follow-ups

- Deferred tools and their triggers:
  - YuNet face detection, if picture-in-picture reactions slip past vision;
  - sentence embeddings, if the contribution scale does not calibrate;
  - Qwen3-ASR, if Indonesian transcripts are poor;
  - audio fingerprints, to confirm a subject once it is acquired.
- Persist the transcript for Stage 5b and narration.
- The subject of an original reaction as footage (Stage 5b).
- "Other accounts repost this reaction" as a discussion signal (Stage 8 story search).
