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
in a plain `span.cap-break-words`, which `PROMPT_JS`'s span fallback reads — the whirl
fixture therefore exonerates the span heuristic for the 2026 TUXModal shape, and production's
`subtype=unknown` most plausibly comes from prompt wording/locale never matching
`CLICK_PROMPTS` (or a late-rendered prompt); the samples will settle it.

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
