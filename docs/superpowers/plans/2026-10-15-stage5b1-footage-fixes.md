# Stage 5b.1 Footage Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix what the live calibration of Stage 5b showed: figures get real footage of the
figure, TikTok clips download, a stuck candidate check can no longer stall the stage, and the
operator's labels are locked as goldens.

**Architecture:** Changes stay inside the `footage/` package (queries, vision judge, downloader,
builder) plus one tiny change to the shared vision reader's log text. No schema change: the
person flag travels inside the stored objects JSON with a default.

**Tech Stack:** Python 3.12, asyncio, Agno over OpenRouter, yt-dlp, the existing TikWm resolver,
pytest.

**Spec:** `docs/superpowers/specs/2026-10-14-stage5b-footage-design.md`, section
"Addendum 5b.1" (operator-approved 2026-10-15). Evidence: the calibration ledger
`.superpowers/sdd/2026-10-15-stage5b-footage/progress.md` and
`D:/thoth-tmp/bu/s8/calibration.json`.

## Global Constraints

- All Stage 5b constraints and rulings P1-P5 still hold (context file
  `.superpowers/sdd/2026-10-15-stage5b-footage/context.md`).
- At most 4 queries per run; with a person, the person query is one of them (objects 3 + 1).
- The story threshold stays 0.33 (calibration decision).
- Downloads stay direct (no account proxy). TikWm calls go through the shared
  `SHARED_TIKWM_RATE_GATE` (1 s).
- A stuck check never holds the stage past its deadline; the activity never reaches its
  20-minute `start_to_close`.
- Logs: counts, platform, stage names, class names only; never captions, URLs, or queries.
- No new dependency. Tests offline. Commits: one-line subject, no body, no trailer.

## Review Focus

1. A person story whose only footage is the person speaking at an event — admitted, not
   rejected as commentary (Task 1). An overlay-banded clip is never admitted (Task 1).
2. A commentator talking about the person — still rejected as commentary (Task 1).
3. TikWm rate-limited or unavailable — that candidate is `media_failed`, the stage continues
   (Task 2).
4. A judge that swallows cancellation — the stage still finishes by its deadline, and the
   stuck stage is named in a warning (Task 3).
5. A run resumed from objects stored before this change (no `person` key) — still works
   (Task 1).

---

### Task 1: Real footage of a figure

**Files:** `footage/models.py`, `footage/queries.py`, `footage/adapters/vision.py`,
`footage/ports.py`, `footage/service.py`; tests in `tests/footage/test_queries.py`,
`tests/footage/test_clip_adapters.py`, `tests/footage/test_service.py`.

**Behavior:**
- `FootageObject` gains `person: bool = False` (stored objects without the key still load).
- The query prompt asks again for PEOPLE (Scout's rule 3: well-known figures closely tied to
  the subject, 0-2, empty when unsure). `FootageQueryAnswer` gains `people: list[str]`
  (null → empty, coerced to str). `footage_objects`: when at least one person is named, the
  result is the first 3 objects plus one person object
  `FootageObject(query=compose_query(f"{person} pidato", subject)[:100], visual="<person> in person: speaking at an event, a press conference, or a visit", person=True)`
  — the word "pidato" steers the search to raw speech and press-conference uploads (official
  channels usually post them without burned-in subtitles; operator decision D, 2026-10-15);
  without a person, up to 4 objects as today.
- `FootageJudge.judge(frames, visual, *, person: bool = False)`. For `person=True` the prompt
  says: kind is `footage` when the video shows that person themself — speaking at an event,
  a press conference, a visit, an interview they give; `commentary` only when someone else
  talks about them, a news anchor, a slideshow, or a reaction. For `person=False` the prompt
  is unchanged.
- The builder passes `person` for each candidate from its query's stored object (a map
  query → object built from the run's objects; carousel candidates pass False).
- Footage whose OCR outcome is `overlay` (a persistent burned-in band) is rejected with the
  existing reason `subtitle`, like a subtitled clip: the renderer blurs bands on the main only,
  so an overlay band on a cutaway would show (2 of the 18 calibration clips). Operator,
  2026-10-15: until the renderer blurs footage (not planned now).

**Tests:**
- `footage_objects` with people: 3 objects + the person object (flag True, visual as above);
  without people: up to 4 objects; null `people` tolerated.
- `FootageObject.model_validate({"query": "q", "visual": "v"}).person is False`.
- The judge prompt for `person=True` contains the person exception text and the visual; for
  `person=False` it equals today's prompt.
- Builder: a candidate under the person query is judged with `person=True` (fake judge
  records the flag); a normal query with `person=False`.
- `footage_objects` with a person and subject `kemang`: the person query is
  `"<name> pidato kemang"`.
- Builder: an OCR outcome `overlay` → rejected `subtitle`, window deleted, judge not called.

### Task 2: TikTok clips through TikWm

**Files:** `footage/adapters/downloader.py`, `activities/footage.py`
(`build_production_footage`); tests in `tests/footage/test_clip_adapters.py`.

**Behavior:**
- Calibration evidence: yt-dlp gets HTTP 403 on TikTok pages from this host, with or without
  impersonation (43 of 87 TikTok checks failed).
- `YtDlpClipDownloader` takes an optional `resolve_tiktok: Callable[[str], Awaitable[str]]`.
  For a `tiktok.com` URL it first resolves the direct video URL through it, then downloads
  that direct URL with the same yt-dlp options and window (the generic extractor handles a
  direct mp4). A resolver error (`TikWmError` or any exception) is a `ClipError`. Other
  platforms are unchanged.
- Production wiring: `resolve_tiktok` uses `TikWmResolver` (`acquisition/adapters/tikwm.py`)
  with `SHARED_TIKWM_RATE_GATE`, returning the resolution's download URL (read the resolver to
  find the field name).
- The direct URL is never logged.

**Tests:**
- A TikTok URL: the resolver is called once with it, and yt-dlp receives the resolved URL (fake
  `_run_yt_dlp` records it) with the window options.
- A resolver raising → `ClipError`, nothing left in the target folder.
- A YouTube URL: the resolver is not called.

### Task 3: A stuck check never stalls the stage

**Files:** `footage/service.py`, `attribution/adapters/vision.py` (log text only); tests in
`tests/footage/test_service.py`, `tests/attribution/` (adjust only if a test pins the text).

**Behavior:**
- Calibration evidence: in one run a candidate check stayed alive 12 minutes past its 90 s
  timeout (cancellation not honored inside), so the 720 s deadline never applied and the
  activity hit its 20-minute `start_to_close`.
- Each check records its current step (`download`, `ocr`, `frames`, `vision`, `hash`,
  `store`). On the per-candidate timeout the check task is cancelled and given a short grace
  (10 s); if it is still not done it is abandoned: the candidate is recorded `media_failed`,
  a warning names the platform and the stuck step (no URL), and the batch continues. An
  abandoned task's later store writes are ignored (a per-build "closed candidates" set checked
  before `admit`/`reject`).
- The whole build runs under a hard deadline of `deadline_seconds + 120` (search included);
  when it fires, the run finishes with what was admitted (`ok`/`none`) and a warning names the
  phase (`search` or `checks`).
- `AgnoVisionReader` log lines say "vision read unavailable" / "vision read unusable" without
  "attribution stops" (the reader is shared with footage).

**Tests:**
- A judge that catches `CancelledError` and keeps sleeping: with `per_candidate_seconds=0.2`,
  the build returns within about a second, the candidate is `media_failed`, the warning names
  step `vision`, and a later attempt by the abandoned task to admit is ignored.
- A search port that never returns: with a tiny deadline the build finishes with status
  `unavailable` (nothing searched) and a warning naming `search`.

### Task 4: Calibration goldens

**Files:** `tests/fixtures/footage/calibration_2026-10-15.json`,
`tests/footage/test_calibration_golden.py`.

**Behavior:** a fixture holding, per calibration story, the story text the builder embedded
(`f"{text[:120]}. {text}"` of the main post) and the labeled candidates: caption, recorded
story score, decision, and the operator's label (`relevant`/`irrelevant`) from the ledger. The
real-model test (fails, not skips, without `THOTH_TEST_EMBEDDING_MODEL_DIR`) asserts each
recorded score is reproduced within 0.02, and that at threshold 0.33 the labeled relevant
admitted clips stay above it. Build the fixture from `D:/thoth-tmp/bu/s8/calibration.json`, the
workflows' source reports (read through the worker container), and the labels recorded in the
ledger; only public post text, no media, no URLs beyond the post URLs.

### Task 5: Records and verification

Full suite through the WSL runner, ruff, CHANGELOG entry "2026-10-15 - Stage 5b.1: footage
fixes from calibration" with the calibration numbers, the label analysis, the decisions, and
**Next steps** (PR, CI, deploy, re-run the calibration stories to compare; follow-ups: attribution
without a credit, structured INFO logging for footage).
