# Stage 5b: Footage in Python — Design

Status: design approved by the operator section by section on 2026-10-14; this written spec
awaits the operator's review.

Research: `docs/research/2026-10-14-stage5b-footage-research.md` (tools, optimizations, and the
revised frame checks in its section 9).

## 1. Goal

Add footage (cutaway b-roll) to the Content Set without Scout: up to six short video clips that
show the concrete things the story is about, found by keyword search on TikTok, YouTube, and X,
or taken from the main's own Instagram carousel. Each clip is gated cheap-to-expensive, checked
on its frames, cut to the window the renderer uses, and recorded in PostgreSQL so a retry resumes
instead of starting over.

## 2. Scope

In scope:

- Query extraction (port of `scout/lib/footage_objects.ts` and `scout/pipeline/footage_queries.ts`
  without the dossier branch).
- Keyword search: TikTok (existing `acquisition/discovery.py`), YouTube (`yt-dlp` search), X
  (signed-in search page, video filter).
- The main-carousel shortcut for video slides.
- Text gates ported from `scout/pipeline/build_footage.ts`; a local-embedding story gate.
- Frame checks: the 5a subtitle classifier, one vision call, and a duplicate check.
- Windowed downloads.
- PostgreSQL state (three tables, ORM, Alembic) and the `footage` items of `ContentSet` v1.
- A `build_footage` activity and a `footage` stage in `SourceInvestigationWorkflow`.

Out of scope (section 13): post cards and photo slides (5c), creator-profile footage (5c),
Instagram, Threads, and Facebook keyword search, stock footage, moving the existing JSON reports
to PostgreSQL, and the dashboard reading the new artifact.

## 3. Decisions (operator, 2026-10-14)

1. Scope A: video b-roll first; post cards and creator-profile footage are 5c.
2. No stock footage (Pexels paused new API keys; no stock dependency).
3. One vision call per candidate is a hard gate (reaction or commentary, object not shown) and
   writes the clip's description. CLIP and face detection are not used (research section 9).
4. At most six footage items per Content Set and two per query; the search stops when six are
   admitted.
5. Footage state lives in PostgreSQL; media stay files. The existing JSON reports move to
   PostgreSQL in a separate spec.
6. Footage is its own activity and stage, before assembly (approach 2).
7. Media downloads go direct, without the account proxies (the current materializer behavior);
   only signed-in searches use an account's proxy.
8. Queries come from the LLM extraction only until Stage 6 provides a dossier.

## 4. Architecture

```text
SourceInvestigationWorkflow
  source -> attribution -> footage (new) -> assembly

footage/
  service.py        FootageBuilder: run, resume, quota, ordering
  queries.py        LLM extraction (Agno over OpenRouter), structured output
  gates.py          pure text gates (ported from Scout) and the story gate
  frames.py         frame sampling, subtitle OCR (5a), duplicate hashes
  models.py         FootageRun, FootageCandidate, Footage (Content Set item)
  ports.py          SearchPort, VisionPort, Embedder, FrameSampler, ClipDownloader, FootageStore
  adapters/
    tiktok.py       wraps acquisition/discovery.py keyword discovery
    youtube.py      yt-dlp ytsearch
    x_search.py     signed-in search page, video filter (x_discovery.py pattern)
    vision.py       footage prompt through the Stage 4 vision reader
    embedder.py     fastembed, paraphrase-multilingual-MiniLM-L12-v2
    downloader.py   yt-dlp with --download-sections
infrastructure/
  footage_models.py ORM rows
  footage_store.py  repository (FootageStore)
activities/
  footage.py        build_footage activity
```

The package boundary follows `assembly/`: domain logic behind ports, adapters at the edge, the
activity composes them. Search adapters reuse the acquisition service, its leases, policies,
cooldowns, and budgets; they never open a browser of their own.

### Temporal integration

- `build_footage` runs after attribution and before `assemble_content`, only when
  `THOTH_FOOTAGE_ENABLED` is true. It receives the same inputs as assembly: the source report,
  the attribution result, and the original's report.
- Timeouts: `start_to_close` 20 minutes, heartbeat 2 minutes, at most 3 attempts.
- Events: `STAGE_STARTED` and `STAGE_COMPLETED` for stage `footage`. A failure after all attempts
  emits a warning event; the workflow continues and assembly records `footage_status =
  "unavailable"`.
- `assemble_content` reads admitted candidates from `FootageStore` by workflow id.

## 5. Flow

### F1 Main and inputs

The main is the one assembly uses (5a A2): the original when attribution replaced it, else the
input. Footage reads its title, description, cover headline (attribution's `cover_vision`
evidence), its top 12 comments by likes, and its frames (for the duplicate check).

### F2 Carousel shortcut

When the main is an Instagram `/p/` post whose acquisition holds at least two video slides,
footage is the other video slides (the first slide is the main), at most six, and nothing is
searched. Each slide still passes F7 (subtitle OCR, vision, duplicate). Fewer than two video
slides: the normal flow runs.

### F3 Queries

One structured call through Agno over OpenRouter (`THOTH_FOOTAGE_QUERY_MODEL`, default the
figures model `deepseek/deepseek-v4-flash-0731`). Prompt ported from `footage_objects.ts`
(rules unchanged, translated to English), with one change: each object returns two strings.

- `query`: the Indonesian search query, the object joined with the primary subject as Scout's
  `composeQuery` does, generic terms expanded to concrete brands or places.
- `visual`: one English sentence describing what the object looks like on screen, for the
  vision check.

At most four objects. The result is stored in `footage_runs` before any search, so a retry never
calls the model again. No usable answer after one retry: `footage_status = "unavailable"`.

### F4 Search

Platforms run concurrently; queries within one platform run in order. Each query asks for up to
8 results per platform.

| Platform | Access | Route |
|---|---|---|
| TikTok | the platform's policy (anonymous first, a lease when thin) | `discovery.py`, `kind="keyword"` |
| YouTube | anonymous, no proxy | `yt-dlp` `ytsearch8:<query>`, flat extraction |
| X | a signed-in lease with its proxy, spacing, and budget | `x.com/search?q=<query>&f=video`, list responses read in page |

Results are cached in `footage_searches` for 24 hours, keyed by platform and normalized query
(lowercased, whitespace collapsed). A cached entry is used without touching the platform.

A platform that fails (captcha, cooldown, exhausted budget, no account, timeout) contributes no
candidates; one warning with the platform and a reason enum. All platforms failing:
`footage_status = "unavailable"`.

### F5 Text gates

In this order; none of them touches media. Ported from `build_footage.ts` unless noted.

1. **Main identity:** same URL, same platform id (`videoId`), or a caption contained in the main's
   title and description or the reverse (normalized, over 20 characters).
2. **Seen:** a URL already recorded for this workflow.
3. **Aggregator:** the owner is on the curated list attribution already loads
   (`attribution/candidates.py`).
4. **Spam:** link-first text or a known spam or shortener domain (Scout's regex).
5. **Reaction text:** Scout's `REACTION_RE`.
6. **Duration** (new): between 3 seconds and 15 minutes when the platform reports it.
7. **Story gate** (moved earlier): cosine between the main's story (`title. description`) and the
   candidate's caption with the local embedder; at least `THOTH_FOOTAGE_STORY_MIN` (default 0.33,
   calibrated in section 10). An empty caption fails it.

Each rejection is stored with its reason.

### F6 Order and quota

Candidates that passed F5 are ordered by story score within their query. Selection takes them in
rounds across queries (first candidate of each query, then the second), at most two admitted per
query and six in total, and stops as soon as six are admitted.

### F7 Frame checks

At most three candidates at a time, each within 90 seconds.

1. **Sample:** resolve the stream (`yt-dlp`, no download) and decode the 5a sample times with
   ffmpeg seeks on the stream. Coverage must be complete, as in 5a.
2. **Subtitle OCR:** the 5a classifier and its corrections. `subtitle` is rejected (the renderer
   refuses subtitle-classified footage); `clean`, `cover`, and `overlay` keep their trim, mute,
   and blur.
3. **Vision:** one structured call on three frames after `trim_start`, through the Stage 4 vision
   reader (`THOTH_SOURCE_VISION_MODEL`), with a footage prompt that answers:
   - `kind`: `footage` or `commentary` (the Stage 4 classes; commentary covers a person talking
     to the camera, a news anchor, a slideshow, and a reaction). `commentary` is rejected.
   - `shows_object`: `yes`, `partly`, or `no` against the object's `visual`. `no` is rejected.
   - `description`: one sentence on what the clip shows (at most 300 characters).
4. **Duplicate:** a 64-bit difference hash (dHash) of each sampled frame. A candidate whose frames
   match the main's or an admitted clip's (Hamming distance at most 10 on at least half the
   frames) is rejected as `duplicate`.

A media failure (stream, probe, incomplete coverage) rejects the candidate as `media_failed`; a
vision error or timeout as `vision_unavailable`. Neither stops the stage.

### F8 Download

- A clip of 30 seconds or less is downloaded whole.
- A longer clip is downloaded from `trim_start` for 15 seconds with
  `yt-dlp --download-sections`; `clip_start` records where the window begins in the source, and
  the stored OCR is shifted to the window.
- Direct, without an account proxy. Written to
  `reports/<workflow_id>/footage/<sha256(url)[:20]>.mp4` through `.part` and `os.replace`.
- The checksum, size, and duration are recorded; the candidate becomes `admitted`.

### F9 Finish

`footage_runs` records `footage_status`: `ok` with at least one admitted clip, `none` when
candidates existed but none was admitted, `unavailable` per F3 and F4. Twelve minutes into the
stage, the run stops and keeps what was admitted.

## 6. Output contract

### Content Set

`ContentSet` stays `schema_version: 1`; `footage` was reserved as always empty in 5a.

```text
ContentSet (additions)
  footage: list[Footage]                 max 6
  footage_status: ok | none | disabled | unavailable

Footage
  source: search | carousel
  url, platform: tiktok | youtube | x | instagram
  owner_handle, published_at?, engagement
  query: str                             the Indonesian search query, or "carousel"
  visual: str                            max 300, the object's English visual description
  caption: str                           max 2000, the post's own text
  description: str                       max 300, what the clip shows (vision)
  video: MediaRef                        video/mp4
  clip_start: Seconds
  ocr: MainOcr
  story_score: float                     0..1 (1 for a carousel slide)
  shows_object: yes | partly
```

Validators:

- `footage_status == "ok"` exactly when `footage` is non-empty;
- no two items share a URL, and no item's URL is the main's;
- `ocr.outcome != "subtitle"`;
- `video.media_type == "video/mp4"`.

Assembly builds the list from admitted candidates in order. Figures (5a A5) also read the footage
descriptions, as Scout's `extract_figures` does.

### Mapping for the renderer (later sub-stage)

The renderer's `ContentResult` maps: `url`, `platform`, `query`, `description`, `is_video = true`,
`duration_sec` from `video.duration_seconds`, `relevance = "match"`, `trim_start`, `mute_audio`,
and the blur from `ocr`. A converter is out of scope here (5a section 12 lists it).

## 7. Persistence

Control-plane PostgreSQL (the database that holds the source account tables), SQLAlchemy ORM,
one Alembic revision in the editor migration chain.

### `footage_searches`

| Column | Type | Notes |
|---|---|---|
| `id` | uuid | primary key |
| `platform` | text | `tiktok`, `youtube`, `x` |
| `query` | text | normalized |
| `results` | jsonb | list of public post summaries: url, platform, owner, caption (max 2000), published_at, engagement, duration |
| `fetched_at`, `expires_at` | timestamptz | `expires_at = fetched_at + 24 h` |

Unique `(platform, query)`. Expired rows are deleted whenever a search is written.

### `footage_runs`

| Column | Type | Notes |
|---|---|---|
| `workflow_id` | text | primary key |
| `status` | text | `running`, `done` |
| `footage_status` | text | section 6 |
| `objects` | jsonb | F3 result: list of `{query, visual}` |
| `started_at`, `finished_at` | timestamptz | |

### `footage_candidates`

| Column | Type | Notes |
|---|---|---|
| `id` | uuid | primary key |
| `workflow_id` | text | references `footage_runs`, cascade delete |
| `url`, `platform`, `query`, `source` | text | |
| `owner_handle`, `caption`, `published_at`, `engagement` | | public post fields |
| `status` | text | `pending`, `admitted`, `rejected` |
| `reason` | text | null unless rejected: `main`, `seen`, `aggregator`, `spam`, `reaction_text`, `duration`, `story`, `subtitle`, `commentary`, `object_absent`, `duplicate`, `media_failed`, `vision_unavailable` |
| `story_score` | real | |
| `kind`, `shows_object`, `description` | text | vision answer |
| `media_location`, `media_checksum`, `media_bytes`, `duration_seconds`, `clip_start` | | set when admitted |
| `ocr` | jsonb | `MainOcr` |
| `position` | int | admission order |
| `created_at`, `updated_at` | timestamptz | |

Unique `(workflow_id, url)`. Never stored: CDN URLs, cookies, proxies, prompts, or raw model
output.

## 8. Resume and idempotency

- `footage_runs` exists: its `objects` are reused; F3 is not called.
- `admitted` candidates are kept when their file exists with the recorded checksum; otherwise the
  candidate returns to `pending`.
- `rejected` candidates are skipped; `pending` ones are processed again.
- Searches come from the 24-hour cache.
- Clip file names derive from the URL, and writes go through `.part` and `os.replace`, so a retry
  never duplicates a file. Cancellation removes `.part` files.

## 9. Configuration and degradation

| Setting | Default | Notes |
|---|---|---|
| `THOTH_FOOTAGE_ENABLED` | `false` | off: the stage is skipped, `footage_status = "disabled"` |
| `THOTH_FOOTAGE_QUERY_MODEL` | `deepseek/deepseek-v4-flash-0731` | F3 |
| `THOTH_FOOTAGE_STORY_MIN` | `0.33` | F5 step 7, calibrated |
| `THOTH_EMBEDDING_MODEL_DIR` | `/opt/thoth/models/embedding` | fastembed cache, baked in the image |

The vision model is `THOTH_SOURCE_VISION_MODEL`; the key is `THOTH_OPENROUTER_API_KEY`.

With footage enabled, the worker refuses to start when ffmpeg, RapidOCR, OpenCV, the embedding
model, or the OpenRouter key is missing (operator rule: a missing required tool is an explicit
error). At runtime, failures degrade as F3, F4, and F7 describe; a failure of the whole activity
never fails the workflow.

Logs: `info` for counts per platform and per rejection reason, `warn` for degradation. Never a
caption, a CDN URL, a cookie, or a proxy.

## 10. Testing and calibration

Offline, in the suite (the `conftest` guard blocks non-loopback requests):

1. Scout parity for the spam and reaction regexes, main identity (`videoId` and the caption
   rule), and `composeQuery`, with a fixture generated from Scout's own functions (the 5a
   method).
2. Gates and quota as pure functions: gate order, no media touched before F5 passes, two per
   query, six in total, rounds across queries.
3. Ports with fakes: platform failure, vision timeout, broken media, each with its reason.
4. Resume: a run stopped midway; the retry calls neither the LLM, nor search, nor vision for
   decided candidates, and redoes an admitted candidate whose file is gone.
5. `FootageStore` on PostgreSQL, the way the source account store is tested: uniqueness, cache
   expiry and pruning, admission order.
6. Workflow: `footage` runs before `assembly`; a footage failure does not fail the workflow; the
   flag off gives `disabled`.
7. Content Set validators (section 6).
8. One test with the real embedding model; a missing model fails with an explicit message.
9. Container contract: the embedding model is fetched in the heavy layers before the source; the
   worker start check covers footage's required tools.

Calibration (an operator-authorized live gate, as 5a's OCR calibration): about five real stories
the operator chooses, spanning a brand, a place, a person, and an event. Search results, frames,
and vision answers are recorded as fixtures; the operator labels which clips are usable b-roll;
`THOTH_FOOTAGE_STORY_MIN` is set from the labels and the vision gate confirmed; the labels become
goldens replayed offline. The end-to-end live smoke waits for the final acceptance (ADR 0001).

## 11. Departures from Scout

- No dossier branch (Stage 6 is not ported); the LLM extraction is the only query source.
- No Instagram or Facebook keyword search; YouTube search is new; X search returns videos only.
- The story gate runs before any media is touched, on local embeddings instead of a provider.
- Reactions are caught by vision as well as by keywords.
- Relevance is checked on frames (`shows_object`), not by caption tokens alone; Scout's token
  rule applied only to posts, which are 5c.
- A duplicate check on frames is new.
- Downloads are windowed; the description comes from vision, not the caption.
- At most six items, two per query; Scout had no total cap.
- State and resume live in PostgreSQL; Scout rewrote the content-set JSON after each object.

## 12. Operator gates

- Push, merge, CI, image pin, and deploy, each separately.
- The calibration capture (live searches and vision calls on real stories).
- Turning `THOTH_FOOTAGE_ENABLED` on in the deployed stack.

## 13. Follow-ups

- 5c: post cards (X, Threads, Instagram), carousel photo slides, creator-profile footage.
- Move `source-report.json`, `source-attribution.json`, and `content-set.json` to PostgreSQL.
- The dashboard Content Set page and Studio import read the new artifact; a converter to the
  renderer's `ContentResult`.
- Footage queries from the Stage 6 dossier once it exists.
