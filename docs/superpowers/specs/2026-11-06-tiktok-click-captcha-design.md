# TikTok click-captcha solver — design (Phase A record)

Branch `feat/tiktok-click-captcha` from `chore/e2e-trial` (88a91037). Executor prompt
2026-11-06, phase A only: evidence capture offline, then a hard stop. Phase B (the solver
itself) starts only after real samples exist and the operator says go.

## Problem

Some creators' profile listings stop on a click captcha the solver cannot answer, so the run
gets no videos and no profile page. Live run `wf_47a20dd1bcbeaf5f8c1f29cd` (2026-11-06,
`kabinet_rakyat`) met the modal three times; each ended
`tiktok captcha outcome subtype=unknown solved=false attempts=1 reason=unsupported`, and
`reason=no_grid` crop misses came before it because the modal was already up at the first
crop. No click modal had ever been recorded before that day — no DOM, no images, no prompt
text — so nothing the solver could be tuned against existed.

## Rule: recording before solving

The keyword table in `captcha.py` came from seller documentation and has never matched a
real modal. Building or tuning a solver from docs or guesses is therefore banned by the
executor prompt. The order is fixed:

1. Production code captures one sanitized sample per unanswerable modal (Phase A, built).
2. Samples reach stage1 only through the operator's gates: passive (push + deploy, normal
   runs collect) or active (an authorised live recording session). Neither is authorized yet.
3. Samples are read before the answer is designed; every "unverified" mark a sample settles
   is updated in this spec.
4. Phase B then builds the smallest solver the samples justify. An unexpected subtype stops
   the work for a report, not a guess.

## Evidence capture (Phase A, built)

`captcha.py` now records what an unanswerable modal shows, inside `solve()`'s existing
contract — never raises, one INFO outcome line per call, no new outcome reasons, no new
settings:

- **Trigger:** `_attempt` meets a modal with no drag handle (today's `unsupported` path —
  every click subtype, classified or not). A later click-solver's failure path will call the
  same `_capture_sample`.
- **Gate:** `THOTH_CONTROL_PLANE_ARTIFACT_ROOT` (compose sets it on the worker). Unset means
  no capture and no writes anywhere, so tests and plain dev runs stay clean.
- **Budget:** the whole capture is bounded by `asyncio.wait_for` at 5 s; any failure logs at
  debug and the solver proceeds unchanged (test-proven: a container whose `evaluate` throws
  still ends `reason=unsupported attempts=1`).
- **Sample:** one directory `<root>/captcha-samples/<utcstamp>/` holding `sample.json`
  (`captured_at`, `subtype`, `reason`, `prompt_candidates` — exactly what the production
  `PROMPT_JS` reader saw — `boxes` of every `img`/`canvas`/`button` and of the prompt span,
  an `images` list, and a `visuals` record), `dom.html` (the container's outer HTML with
  attribute values that are `data:`/`blob:`/protocol-relative URLs, contain `://`, or exceed
  200 chars blanked, and every `url(...)` payload inside a `style` value blanked while the
  rest of the style stays; capped at 200 KB), every modal image as served through the
  existing `_src_bytes` (data URLs decode, links fetch on the session; first 12), a dump of
  each `<canvas>` in the container (`canvas-<n>.png` via `toDataURL('image/png')`; a
  tainted canvas is skipped quietly), and `modal.png` — a screenshot clipped to the union of
  the rendered boxes of the container's `img`, `canvas`, `button` and prompt-span elements,
  never the full viewport or a full-screen overlay's box, so the page behind it (the
  creator's handle) stays out of the sample. An empty union saves no screenshot; a failed
  screenshot loses nothing else. Each image entry carries `src_hint` — the `3d`/`icon`
  marker TikTok bakes into some captcha image URLs — because the sanitized DOM no longer
  keeps the URL itself. Data and blob URLs carry no hint, and their base64 payloads are
  never scanned for one. The element-screenshot ban is a **solving** rule (overlap would
  corrupt a match); for evidence the clipped `modal.png` is exactly the fallback a
  canvas-drawn challenge needs.
- **Bound:** the newest 50 samples are kept; older directories are removed after each write.
- **No secrets:** no cookies, no page URL, no creator handle is recorded; the modal's own
  parts are the only things read. One unfetchable image cannot lose the sample.

Tests: `tests/acquisition/test_captcha.py` (fake pages; one test caught a real bug — a base64
payload can contain `/3d`, so only real URL paths are read for the marker) and
`tests/acquisition/test_captcha_browser.py` (real Chromium on the recorded whirl DOM with its
slider stripped: prompt, boxes, sanitized DOM and both WebP images land in the sample).

## Prompt reading: verified on the whirl modal only

The recorded whirl modal (`tests/acquisition/fixtures/whirl_modal.html`, a 2026 TUXModal) has
no `.captcha_verify_title`; its prompt lives in a plain `span.cap-break-words`. A real-
Chromium test proves `PROMPT_JS`'s span fallback reads that prompt ("Drag the slider to fit
the puzzle"). What that verifies is narrow: no click modal has ever been seen, so whether a
click modal's prompt is read at all is unknown. The leading guess, marked as a guess, is a
keyword-table miss — an Indonesian prompt the seller-derived table does not contain (e.g. a
"bentuknya sama" wording misses "bentuk yang sama") — with a late-rendered or differently
structured click prompt not ruled out. The keyword table stays untouched; the samples will
settle the real wording per locale. A Phase B candidate from the research: classify by the
image URL's `3d`/`icon` marker (see below) instead of prompt keywords.

## What the primary sources say about the two click subtypes

Researched 2026-11-06 from sellers' public docs and open-source solver code only. Tags:
[gbiz123] = github.com/gbiz123/tiktok-captcha-solver (code + two recorded 2026 DOM fixtures),
[sadcap] = sadcaptcha.com docs/swagger, [capzy] = capzy.ai/solvers/tiktok,
[ttcap] = github.com/lumaaaaaa/ttCaptchaSolver (Go, request-level verify). Nothing below has
been seen on our own real sample yet; every item is **unverified until a sample says so**.

Shared:

- Both click subtypes rise in the same modal as the drag ones (`.captcha-verify-container`)
  [gbiz123 fixtures]. Not a grid: one flat `<img>` is clicked at coordinates
  [gbiz123, sadcap, capzy].
- The verify request carries click coordinates with relative times and pointer-trajectory
  models (`reply`/`models` arrays) [ttcap, shown for slide; click application inferred] —
  matching the prompt's humanized-click requirement.
- Maintained solvers click with real mouse events, randomized human timing, and stealth
  browsers [gbiz123]; answers are bound to device, cookies and session, so no token can be
  reused [capzy].

3D shapes ("pick the two same-shape objects"):

- Prompt (verbatim, English fixtures): "Select 2 objects that are the same shape" [gbiz123].
  Indonesian wording: not found in primary sources.
- DOM: prompt in the header span; one `<img class="cap-rounded-lg cap-cursor-pointer
  cap-w-full cap-h-auto" draggable="false">` inside `div.cap-relative`; a `TUXButton--primary
  ... TUXButton--disabled cap-w-full` "Confirm" button (initially `aria-disabled="true"`)
  with selector `.captcha-verify-container .cap-relative button.cap-w-full` [gbiz123]. The
  older `.captcha_verify_slide--confirm` selector appears nowhere in the sources.
- Interaction: exactly 2 clicks at proportional points on the image, then Confirm
  [gbiz123 playwrightsolver.py; sadcap /shapes returns two proportional points].
- Judgment: modal disappears on success; on failure the modal stays and solvers retry (up to
  ~3, with sleeps); 3D retries without pressing refresh [gbiz123]. Pixel tolerance is
  undocumented (one repo's own test uses ±2 px) [gbiz123].

Icon matching ("click the icons that match the instruction"):

- Prompt examples: "Which of these objects has a brim?" [sadcap]; instruction must be sent
  with the image [capzy]. Indonesian: not found in primary sources.
- DOM: same V2 selectors as 3D [gbiz123]; no icon-specific HTML fixture exists.
- Interaction: a variable number of clicks **in order**, then Confirm [gbiz123, capzy]. A
  fixed click count: not found in primary sources.
- Judgment: same verify path; one repo offers end-to-end verify for `slide|whirl|3d` but not
  icon [gbiz123/justscrapeme].

Subtype detection: image URL path containing `/3d` or `/icon` [gbiz123] — but a `blob:` src
breaks that (a fixture proves blob srcs exist) [gbiz123]. Server-side subtype names seen:
`3d`, `slide`, `whirl`, `hashcash` [justscrapeme]; icon's server name not found.

## Solver design for Phase B (decided where samples allow, open where they do not)

Decided now:

- **Classifier:** prefer the image URL marker (`src_hint`) over prompt keywords, falling back
  to keywords, and record both in every sample. The capture already stores `src_hint`, so
  Phase B needs no extra plumbing. Open: what a `blob:` src looks like live.
- **Clicks:** eased pointer moves with jitter and pauses through the existing `_glide`/
  `_settle` machinery, per-point small holds, Confirm clicked only after all points; nothing
  is clicked unless the whole answer is confident.
- **Cost per captcha:** at most a fixed, small number of vision calls per captcha (default 2,
  one per attempt), metered into `usage_events` through the existing OpenRouter path exactly
  as `AgnoVisionReader` meters (`metering.record_model_run`). Model from a new setting
  `THOTH_CAPTCHA_VISION_MODEL` with a default (the same `qwen/qwen3-vl-30b-a3b-instruct`
  the attribution vision path uses). No key → no call → `reason=no_vision` (new reason
  value), solver returns False, discovery keeps today's behaviour.
- **Confidence rule (refuse to click):** the refusal test leans on what can be checked, not
  on a model's self-report. An answer is used only when the reply parses under a strict
  schema and has the right shape — the point count the subtype asks for (exactly 2 for 3D,
  the instruction's count for icon), every point strictly inside the challenge image's
  rendered box, and points distinct from each other for 3D. Success is claimed only when the
  modal really closes after the confirm (the existing `_closed` check); a modal that stays is
  a wrong answer, whatever the model said about itself. A self-reported confidence score is
  at most one extra filter, tuned only on real samples, never the deciding signal. Anything
  unverified returns False with `reason=unconfident` (new reason value) and clicks nothing.
- **Wrong answer:** detected as today — the modal stays after the confirm (existing
  `reason=modal_stayed`), the attempt budget bounds retries, and Phase B's per-captcha call
  budget bounds cost.
- **New outcome vocabulary** (`icon` already exists as a subtype): reasons `no_vision`,
  `unconfident` — to be added to the outcome line's documented vocabulary, the ops counting
  script's expectations if needed, and their tests in Phase B.

Open until samples decide (each named "unverified" above):

- **OpenCV vs the vision model per subtype.** Recommendation: the vision model as primary
  for both (the 3D pair is a rendered-scene similarity judgement; icon needs the instruction
  read), with OpenCV at most as a cheap cross-check for 3D if samples show clean, separable
  renders. If samples show an OpenCV-solvable structure (uniform background, discrete
  shapes), the OpenCV-only path is the cheaper first try. Decided by the samples.
- Real prompt wording per locale; whether `subtype=unknown` was a keyword miss or a
  late-rendered prompt.
- The real click count and whether order matters for icon; whether Confirm is disabled until
  the right number of clicks; whether a wrong answer refreshes the images.
- Whether the modal we meet is one flat image (as every source says) or something else; if
  it is not what the sources describe, Phase B stops and reports instead of guessing.
- Anti-bot tolerance for click timing — the humanized profile is kept regardless.

## Gates

Phase A ends at commit; push, deploy, PR and merge (this branch merges after
`chore/e2e-trial`), live runs and any paid vision call each need the operator's separate
authorization. Approval of an earlier gate never covers a later one.
