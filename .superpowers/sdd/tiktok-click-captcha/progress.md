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

Status: Phase B review applied. Corrected: a refusal does not spare the cooldown — a leased
discovery without videos behind a captcha releases as `challenge` either way. Fixed test-
first: a refusal presses Refresh and uses the remaining attempt (only `unsupported` stops);
pictures are keyed by SHA-256 of their bytes, not src (Chromium proved a re-served blob: got
answered twice before). Verification: captcha + shapes 71 pass, browser 13 pass, full make
test 4613 pass / 221 skip / 0 fail, make lint clean. Next: the same operator gates — push
(new head), deploy with the switch chosen (`local` clicks live, `off` records only), a first
live 3D check limited to creators that raise it, the paid-fallback allowance, icon/Audio.

Status: pushed over SSH port 443 (port 22 and HTTPS dead) and deployed `7a599b48` to stage1
on the operator's approval: thoth `27d727f83a07`, renderer `90157dda5e99`, web `20f4d954aad1`,
rollback `pins-78ac35d3.env`; checks clean; switch unset (default `local`), artifact root
set. Merge on the operator's word: `chore/e2e-trial` as PR #112 first, then this branch.
Next: a first live 3D check on a creator that raises it (any unsolved end steps
`operator-1`'s cooldown), the step-8 check, the paid-fallback allowance, icon/Audio.

Status: first live run on the deploy (`wf_7328e00123c4be15039fe1b7`, kabinet_rakyat): no 3D
modal; a leased whirl missed (166° read, 132.2 px), the second attempt hit unrendered images
(`no_images`), `operator-1` stepped to cooldown level 2; no sample, since capture covered click
modals only. Branch `fix/captcha-drag-evidence`: drag attempts wait up to 4 s for their images,
and slide/whirl challenges are recorded before the drag (deleted when solved, else kept with
the reason). Red first; captcha/shapes/discovery 162 pass, browser 13 pass (also with capture
on), full make test 4616 pass / 221 skip / 0 fail, lint clean. Next: push, deploy the branch
image, merge; a second live run after the cooldown; step 8; paid fallback; icon/Audio.

Status: PR #114 merged (`d2e691f7`, master CI green; tree equals the deployed `7e2701b5`).
Second live run (`wf_4acfca9d3a6cb4c8c698c0c3`, kabinet_rakyat) succeeded: the leased whirl was
solved on attempt 1 (71°, 56.1 px), the pass read 24 videos, `operator-1` back to healthy /
level 0; no sample left (solved drags delete theirs). Still no 3D modal. The profile page was
again not captured (`TimeoutError` after the solve); X search timed out. Next: diagnose the
profile-page timeout offline, a 3D check on a creator that raises it, step 8, paid fallback,
icon/Audio.

Status: root cause of the missing TikTok page card: the anonymous pass cropped it, the leased
pass's screenshot timed out, and the longer leased result replaced the anonymous one whole.
Fixed test-first on `chore/captcha-live-run-2`: a leased miss keeps the anonymous crop (a
leased crop still wins), and a failed crop logs Playwright's message (`detail=`). Checked
offline: the stored 2026-10-27 card is clean; the recorded signed-out page hides its modals.
Full make test 4619 pass / 221 skip / 0 fail, lint clean. Next: push, deploy the branch image,
merge; a live run to see the card and the leased timeout's wait; 3D check; step 8 (look at the
card itself); paid fallback; icon/Audio.
