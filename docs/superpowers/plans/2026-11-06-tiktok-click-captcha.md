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

## Phase B — the solver, after the operator's go (2026-11-06, from one public real sample)

Spec section "Phase B (built)". Basis: `D:/thoth-tmp/research/click-captcha/RESEARCH.md`
(recorded 3D modal, real challenge image, free local spike, operator licence ruling).

1. **Fixtures from the recorded modal:** `shapes_modal.html` (gbiz123 DOM trimmed to the
   modal, source and ruling in the header comment) and `shapes_sample.jpg` (the real
   challenge, 552 × 344, two "8"s hand-labelled at boxes (110,152,55,87) and
   (204,230,36,54)); a real-Chromium shim that enables Confirm after two clicks and clears
   the container only when both land inside the labelled boxes.
2. **Tests first:** structural click detection and the subtype order (URL marker, prompt
   number/`?` rules, keyword table with "bentuknya sama" unverified, unknown); the pure
   solver on synthetic arrays (clean pair, <3 objects, ambiguous pairs, same-colour
   overlap) and the real sample; the refusal paths click nothing (`unconfident`,
   `no_vision`); the pointer profile (eased, jittered, released); Confirm gating and
   `modal_stayed` → Refresh with no second answer to the same image; the vision fallback
   with fakes (strict schema, one call, metering, no key → no call); the switch's `off`.
3. **Smallest solver:** pure `captcha_shapes.py` (hue-peak segmentation, mask-IoU pair
   scoring, PAIR_RATIO refusal, RapidOCR backup vote), the click flow in `captcha.py`
   through the existing `_glide`/`_settle`/`_closed` machinery, the set-of-marks vision
   fallback through the existing OpenRouter path and `metering.record_model_run`, switch
   `THOTH_CAPTCHA_CLICK_SOLVER` (`off`/`local`/`local_vision`, default `local` unless the
   evaluation shows a wrong answer). No new dependency.
4. **Evaluation harness:** a test under `python/tests/` printing per labelled fixture the
   pair or the refusal, real and synthetic cases reported separately.
5. **Verify:** the same commands as Phase A, all green except the three known failures.

Hard stop after Phase B: live runs, paid calls against a real modal, push, deploy, PR, merge
— each needs the operator's explicit authorization.

## Definition of success (unchanged from the executor prompt)

On a real stage1 run, a click captcha ends in `tiktok captcha outcome subtype=<3d|icon>
solved=true`, the listing continues, and the profile page is captured — without random
clicks and without clicking an unread modal.
