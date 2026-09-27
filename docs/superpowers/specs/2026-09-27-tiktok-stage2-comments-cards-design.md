# Stage 2: TikTok Comments and Real Card Artifacts Design

**Status:** Design approved in conversation by the operator on 2026-09-27; written spec awaiting operator review

## 1. Purpose and boundary

Stage 2 of the [Python Scout migration](../../python-scout-migration-roadmap.md) completes the
TikTok vertical slice. This spec covers its first sub-stage: single-post enrichment. The headless
visit already collects comments and crops real TikTok comment cards and the profile header card
(commits `600b435`, `b1798b6`), but the crops live only in memory and are discarded. This
sub-stage makes them durable, checksummed acquisition artifacts recorded in the source report.

Operator decisions that bind this design:

- Collection is anonymous and best-effort. Comments and cards never fail acquisition.
- Cards are real TikTok crops only. There is never a synthetic card, and never a Rust-rendered
  fallback. A card that cannot be cropped or validated is absent.
- Stage 2 stops at the acquisition boundary. The source report is its output. It does not feed
  Creator Studio directly.

Studio has one ingress: a Content Set, projected in the dashboard by `projectStudioSource`
(`dashboard/src/features/studio/content_set_import.ts`) into a path-free
`StudioSourceProjection`. Mapping the report's comments and cards into `comments[].image_path`
and the main item's `profile` is Stage 5 (content assembly). Auto-attaching card images to
Remotion scenes is a separate Studio specification.

## 2. Report schema v2

`TikTokSourceReport` accepts `schema_version` 1 or 2 and writes 2. New fields default to empty,
so every persisted v1 report, including Stage 1 evidence read by `operations/tiktok_parity.py`,
still validates.

```python
class CardArtifact(StrictModel):
    location: PurePosixPath          # relative, e.g. reports/<wf>/cards/comment-<comment_id>.png
    media_type: Literal["image/png"] = "image/png"
    bytes: int                       # 1..MAX_CARD_BYTES
    checksum: Checksum               # sha256:<hex>
    width: int                       # > 0
    height: int                      # > 0

class ReportComment(StrictModel):
    comment_id: str                  # same constraints as TikTokComment
    author: str
    text: str
    likes: int = 0
    card: CardArtifact | None = None

class TikTokSourceReport(StrictModel):
    schema_version: Literal[1, 2] = 2
    ...existing fields...
    comments: list[ReportComment] = []   # at most MAX_COMMENTS (50)
    profile_card: CardArtifact | None = None
```

`CardArtifact.location` uses the same safe-relative-path validator as `MaterializedMedia`.
No image bytes, remote URLs, or avatar URLs are ever serialized.

## 3. Card persistence

After media is materialized, `TikTokAcquisitionService` hands the snapshot's crops to a new
`CardWriter` in the acquisition package. It writes each PNG to
`reports/<workflow_id>/cards/comment-<comment_id>.png` or `.../cards/profile.png`.

- Writes are atomic: `<name>.part`, flush, `os.replace`, the same pattern as the media
  materializer. A retry for the same workflow overwrites the same deterministic name, so it
  never duplicates cards.
- Validation runs before the write, using the standard library only:
  - PNG signature and IHDR width and height;
  - `bytes <= MAX_CARD_BYTES` (2 MiB), width in 31..4096 and height in 13..4096. The lower bounds
    match Scout's `rect.w > 30 && rect.h > 12`;
  - a bytes-per-pixel floor that rejects flat or blank crops. This carries over Scout's
    black-crop guard (`scout/lib/crop_guard.ts`, reject below 0.02). The final threshold is
    confirmed against the statistics of the live capture in section 5.
- A card that fails validation or whose write raises `OSError` is dropped and its comment keeps
  `card=None`. One `warn` log line records only counts: written, rejected, failed.

Comments are kept whenever the headless visit produced them, including when headless media fails
and TikWM rescues the post. The TikWM path itself yields no comments or cards.

## 4. Failure handling and cleanup

- Acquisition failure codes and retryability are unchanged from Stage 1.
- `_cleanup_after_persistence_failure` in `activities/source_investigation.py` also removes every
  card file the report records, with the same resolve-inside-artifact-root check it applies to
  media.
- On cancellation during card writing, the writer removes its `.part` file before re-raising.
- Nothing from comments or cards (text, handles, ids, paths) enters logs, events, or Temporal
  history. Events stay as they are.

## 5. Golden fixtures and offline tests

**Deviation from ADR 0001, approved by the operator on 2026-09-27.** ADR 0001 asks for golden
fixtures recorded once from Scout. For comments, Scout's output now differs from Python only in
behavior the operator deferred: the sticker-only filter, the 12-card cap, and likes parsed from
display text. A Scout reference would therefore measure deferred differences, not correctness.
The golden fixtures for this sub-stage are captured once from real TikTok inputs by the Python
headless visit instead.

- **Capture.** One live run of the branch code against 3 public posts, following the existing
  Stage 2 authorization for a one-time capture. It records the raw `comment/list` pages, the
  text of each cropped DOM card, and width, height, bytes, and bpp for each PNG. Raw output
  stays under `D:/thoth-tmp` and is never committed.
- **Sanitizer.** `python/scripts/sanitize_tiktok_comment_capture.py` is deterministic. It
  replaces handles, ids, and texts with stable pseudonyms and preserves the properties the
  reducer depends on: emoji, length, duplicates, sticker markers, and text equality between API
  entries and card texts. Images are never committed, only their statistics. The sanitized
  fixtures go under `python/tests/fixtures/tiktok/comments/`. The repository is public.
- **Offline tests.** All run under the existing offline guard.
  - Replay: the reducer over the sanitized pages and card texts yields the recorded comment
    set and the same comment-to-card attachment.
  - Card writer: atomic write, deterministic names, checksum, and rejection of a bad signature,
    oversize, out-of-range dimensions, and a flat image. Test PNGs are generated inside the
    tests.
  - Models: a v1 report still validates, a v2 round-trip works, unsafe card locations are
    rejected, and no bytes leak into JSON.
  - Service and activity: comments survive a TikWM rescue, a failed card never fails
    acquisition, and cleanup removes card files.

## 6. Scope

In scope:

- report v2 and `CardWriter`;
- the capture, the sanitizer, and the fixtures;
- the tests;
- correcting the roadmap target diagram. It currently shows `Rust media engine -> validated
  content-set`. Studio renders with Remotion, while the Content Set page still reads through the
  Rust `thoth-server` route `/api/scout/content-set/data`, which must be migrated before Rust
  retires.

Out of scope:

- Content Set mapping (Stage 5) and Studio auto-attach;
- profile discovery, keyword and trending discovery, and engagement and publication-time
  normalization (later Stage 2 sub-stages);
- the deferred minors: the sticker-only filter and the 10 vs 12 card cap. These are recorded in
  the program checkpoint for an operator decision.

No push, deploy, Issue #5 post, or live smoke is authorized by this spec.

## 7. Verification

- The Python suite in WSL (`D:/thoth-tmp/bu/pt.sh`) is green apart from the known unrelated
  `test_route_modules_do_not_depend_on_a_process_runner`.
- `ruff check` and `ruff format --check` are clean.
- The `build_cuda.bat` build passes, or no Rust source changed.
- The program checkpoint and `CHANGELOG.md` are updated.
