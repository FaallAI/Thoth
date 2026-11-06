# TikTok click-captcha — plan

Spec: `docs/superpowers/specs/2026-11-06-tiktok-click-captcha-design.md`. Executor prompt
2026-11-06, phased with hard stops. All tests run from WSL at the worktree root
(`D:/thoth-tmp/wt-click-captcha`); the browser file needs the Playwright-enabled env
(`bash /mnt/d/thoth-tmp/pytest-wsl-browser.sh tests/acquisition/test_captcha_browser.py`),
which CI also covers.

## Phase A — evidence capture, offline (this branch, done)

1. Capture in production code (`captcha.py::_capture_sample`), env-gated on
   `THOTH_CONTROL_PLANE_ARTIFACT_ROOT`, bounded (5 s, 50 samples, 12 images), sanitized,
   never raising, outcome line unchanged. Tests: fake pages in `test_captcha.py`, real
   Chromium in `test_captcha_browser.py`.
2. Prompt-reading proof against the recorded whirl fixture; keyword table untouched.
3. Research record with sources in the spec; unverified marks named.
4. Spec and this plan; checkpoint `.superpowers/sdd/tiktok-click-captcha/progress.md`.
5. Verify: `make test T=tests/acquisition/test_captcha.py`,
   `make test T=tests/acquisition/test_captcha_browser.py`, `make test T=tests/acquisition/
   test_discovery.py`, then full `make test` and `make lint` (3 known `pytest.approx`
   failures in `tests/assembly/test_ocr_replay.py` and `tests/assembly/test_refine.py` are
   pre-existing and untouched).
6. Commit locally; CHANGELOG entry with **Next steps**; hard stop.

## Gates to Phase B (operator, each separate)

- Push and deploy of this branch (passive collection on stage1), or
- an authorised live recording session (active collection), and
- the operator's explicit go for Phase B once samples exist.

## Phase B — the solver, only after real samples and the operator's go

Read the samples first; update every "unverified" mark in the spec. If a sample shows a
subtype or shape the spec did not expect, stop and report.

1. **Fixtures from samples:** sanitized DOM and images under `python/tests/acquisition/
   fixtures/` (click-shaped pages, like the whirl ones), plus real-Chromium shims that clear
   the container only when the right points are clicked in order and Confirm follows.
2. **Tests first:** classification from `src_hint` with keyword fallback and blob-src
   behaviour; the refusal paths (low confidence, unreadable prompt, vision failure, no key)
   click nothing and log `unconfident`/`no_vision`; the pointer profile (eased, jittered,
   released); the outcome line carries the new reasons; the call budget and its metering.
3. **Smallest solver:** classifier, then per subtype — vision model through the existing
   OpenRouter path and `metering.record_model_run`, `THOTH_CAPTCHA_VISION_MODEL` with a
   default, no call without a key; OpenCV only if the samples justify it (see spec). Humanized
   clicks through the `_glide`/`_settle` machinery; Confirm after all points.
4. **Verify:** the same commands as Phase A, all green except the three known failures.

Hard stop after Phase B: live runs, paid calls against a real modal, push, deploy, PR, merge
— each needs the operator's explicit authorization.

## Definition of success (unchanged from the executor prompt)

On a real stage1 run, a click captcha ends in `tiktok captcha outcome subtype=<3d|icon>
solved=true`, the listing continues, and the profile page is captured — without random
clicks and without clicking an unread modal.
