# SDD ledger — TikTok click-captcha solver (Phase A: evidence capture)

Branch `feat/tiktok-click-captcha` from `origin/chore/e2e-trial` (88a91037), worktree
`D:/thoth-tmp/wt-click-captcha`. Executor prompt 2026-11-06, mode IMPLEMENT_PLAN, Phase A
only: offline, no live TikTok requests, no paid model calls. Hard stop after Phase A.

Design decisions (from the executor prompt; spec at
`docs/superpowers/specs/2026-11-06-tiktok-click-captcha-design.md`):

- Recording comes before solving: production code captures one sanitized sample per
  unanswerable modal; real samples reach stage1 only through the operator's push/deploy or a
  live-session gate; Phase B starts only after the operator says go.
- Capture is env-gated on `THOTH_CONTROL_PLANE_ARTIFACT_ROOT` (set in the worker by compose):
  unset means no capture and no filesystem writes anywhere, so tests and plain dev runs stay
  clean. `solve()`'s signature and the outcome line stay unchanged; no new outcome reasons.
- Commercial captcha services stay banned (operator, 2026-10-23). No random clicks.

Status: reading done (captcha.py, discovery.py, tests, fixtures, CHANGELOG entries, vision
path, ops script). The recorded whirl modal has no `.captcha_verify_title`; its prompt lives
in a plain `span.cap-break-words`, which `PROMPT_JS`'s span fallback reads. That verifies the
reader on the recorded **whirl** modal only — no click modal has ever been seen, so whether a
click modal's prompt is read at all is unknown; a keyword-table miss (e.g. Indonesian
wording) is the leading guess, marked as a guess, and the samples will settle it.

Status: Phase A built and verified, one local commit on this branch. Capture in
production code (env-gated on the artifact root, bounded 5 s / 50 samples / 12 images,
sanitized, never raising, outcome line unchanged; one base64 `/3d` false-marker bug caught
red first). Prompt reading proven on the recorded whirl modal in real Chromium; keyword table
untouched. Research recorded with sources in the spec: both click subtypes are one flat
image clicked at coordinates (3D: 2 clicks + Confirm, prompt "Select 2 objects that are the
same shape"; icon: N clicks in order + Confirm); open items named unverified. Tests:
test_captcha.py 35 pass, test_captcha_browser.py 7 pass in Chromium (WSL Playwright env,
`D:/thoth-tmp/pytest-wsl-browser.sh`), test_discovery.py 88 pass; full make test + make lint
green except the 3 known `pytest.approx` failures (test_ocr_replay, test_refine), untouched.
Next: operator gates, each separate — push/deploy of this branch (passive collection) or a
live recording session (active), then the go for Phase B once samples exist. Gates not
authorized: push, deploy, PR, merge (rides after `chore/e2e-trial`), live runs, paid vision
calls.

Status: review round applied (second commit, `f503ced1` untouched). Samples now also carry
`modal.png` (screenshot clipped to the union of the container's img/canvas/button/prompt-span
boxes — never the viewport or a full-screen overlay, so the page behind stays out) and
`canvas-<n>.png` dumps (tainted canvases skipped quietly); a failed screenshot keeps the
sample; `sample.json` records the visuals and the clip. The DOM scrub now blanks `//`- and
`blob:`-prefixed values and `url(...)` payloads inside `style`. All red first (fake pages
KeyError 'visuals'; the Chromium overlay test proven red with the implementation stashed).
The spec's refusal rule leans on checkable shape, strict parsing and the modal closing, not
self-reported confidence. Phase A's dev installs are disclosed in the CHANGELOG with removal
steps. Round verification: captcha 38 pass, browser 8 pass, discovery 88 pass, full make
test + make lint green except the 3 known `pytest.approx` failures. Prompt wording claim
narrowed: reader verified on the whirl modal only; keyword miss is the leading guess. Next:
the same operator gates as above.

Status: Phase B built and verified on the operator's go (2026-11-06, one public real sample
under the licence ruling; no stage1 sample yet). Detection is structural (img in
.cap-relative + Confirm + no handle; blob-safe), the subtype order is url marker → prompt
(number 2 / trailing "?") → keywords ("bentuknya sama" added, unverified) → unknown, source
logged at debug, outcome line unchanged. The local solver `captcha_shapes.py` is pure and
deterministic: hue groups chosen by the image's own histogram, normalised-mask IoU with the
mirror variant, refusal unless ≥3 objects and best < 0.7×second with a 0.05 gap; RapidOCR
backup vote fires only on a margin refusal (reads nothing on the real pastels — unproven).
Click flow: mapped points, two humanized clicks (pointer released in finally), Confirm
after it enables, `_closed` verify, Refresh on modal_stayed, never the same image twice;
samples saved on unconfident/no_vision/modal_stayed; no retry on those reasons. Vision
fallback built fake-only: set-of-marks, strict JSON (two numbers), one metered call per
attempt like AgnoVisionReader, usage_events test-proven, no key → no_vision; no real call
made. Switch THOTH_CAPTCHA_CLICK_SOLVER off/local/local_vision, default local (evaluation:
no wrong answer; margin 0.7 ratio + 0.05 gap). Fixtures: shapes_modal.html (trimmed gbiz123
modal, ruling in header) + shapes_sample.jpg (force-added past *.jpg ignore), two 8s
hand-labelled. Phase A leftover done: modal.png skipped when the clip union covers more
than half the viewport. Verification: captcha 57 pass, shapes 12 pass (harness prints per
fixture, real/synthetic apart), browser 12 pass in Chromium (clear, blob:, refusal-clicks-
nothing, stubborn-refresh-once), discovery 88 pass, full make test + make lint green except
the 3 known pytest.approx failures. Next: operator gates, each separate — push, deploy, a
first live 3D check (wrong answer steps operator-1's cooldown), the paid-fallback
allowance, then icon/Audio follow-ups.
