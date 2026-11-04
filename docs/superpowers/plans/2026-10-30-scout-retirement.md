# Scout Retirement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Remove legacy Scout from the Stage 1 platform: no legacy activity, no activity modes, no `legacy-cdp` service, no Scout in the image, and no `scout/` tree.

**Architecture:** Since master `5d9ee252` (PR #87) acquisition runs Python only, and the operator ruled that Scout must not rescue a failed run (2026-10-30). This plan deletes the dormant paths. The workflow keeps decoding the `activity_mode` field of its input, because the closed histories still in retention carry it.

**Tech stack:** Python 3.12, Temporal, pydantic v2, Docker Compose, GitHub Actions.

**Spec:** the operator's rulings of 2026-10-30. Quoted in `CHANGELOG.md`:

- "scout dan crates itu sudah tidak dipakai!!! karena nanti akan full ke python"
- "ya scout harus mati, nanti jika gagal berarti dari sisi python nya perlu di perbaiki lagi"
- "ya setuju" to a Python-only soak

## Global constraints

**Replay safety: no closed run may stop opening in the dashboard.** A scan of stage1 on 2026-10-30 found:

- 30 workflow histories inside the 30-day retention;
- 27 of them started with `activity_mode="python_tiktok_with_legacy_fallback"`;
- none of them scheduled `inspect_legacy_scout`.

So:

- `SourceInvestigationWorkflowInput.activity_mode` keeps all three literal values, decode-only, until 2026-11-29. The workflow ignores it.
- Removing the legacy branches changes no command those histories recorded.

**Out of scope (separate tasks):**

- `crates/` and the Rust-era docs, which describe Scout and Rust together: `README.md`, `.env.example`, `scripts/`, and the `docs/*.md` pages about the Rust pipeline.
- Historical specs, plans and research are records; leave them.

**Operator gates:** push, merge and deploy are each a separate operator gate.

## Review focus

- **Opening a run from before the retirement:**
  - its input still decodes with the fallback mode;
  - its replay matches its history.
- **A URL on a platform Python does not acquire** (it used to be "legacy"):
  - it is refused at submission as unsupported;
  - it never starts a workflow.
- **Deploy:**
  - the running `legacy-cdp` container is removed (`up --remove-orphans`);
  - no service still waits on it.
- **Image:**
  - no Scout files, no `start-legacy-cdp` and no `gallery-dl`;
  - `bun` stays, because yt-dlp uses it as the YouTube JS runtime.
- **Leftover settings:** a stale `THOTH_STAGE1_ACTIVITY_MODE` in an operator's `.env.stage1.local` is harmless, because compose no longer reads it.

---

### Task 1: Python-only routing in the workflow and the domain

**Files:**
- `workflows/source_investigation.py`
- `acquisition/platforms.py`
- `domain/models.py` and `domain/__init__.py`
- `application/workflows.py`, plus their tests

The changes:

- **Workflow routing:**
  - `_execute_source_activity` returns `unsupported_platform` for anything that is not Python-supported; otherwise it runs the Python activity.
  - Remove `_execute_legacy_activity`, `_report_from_legacy`, the `legacy_source` skip and `_legacy_fallback_event`.
- **Platform support:** `platform_support` returns `"python" | "unsupported"`.
- **Domain model removals:**
  - `LEGACY_FALLBACK_ELIGIBLE_CODES`;
  - the `fallback_from` payload key and its check;
  - the `legacy_source` skip reason;
  - the `LegacyScoutProgressEvent` alias.
- **`SourceActivityMode`:** stays, with a decode-only comment and its removal date.
- **Tests:**
  - routing tests assert the Python-only behavior;
  - legacy-path tests are deleted;
  - a replay-style test checks that an input with `python_tiktok_with_legacy_fallback` still runs the Python path.

### Task 2: Remove the legacy activity, worker adapter and mode setting

**Files:**
- `activities/legacy_scout.py` (delete) and `activities/__init__.py`
- `worker.py`, `config.py` and `infrastructure/temporal_gateway.py`
- `operations/stage1_local_preflight.py`, plus their tests

The changes:

- The worker runs one `Worker` on the control-plane queue, with no legacy adapter queue.
- `THOTH_SOURCE_INVESTIGATION_ACTIVITY_MODE` and the gateway's `activity_mode` parameter are removed.
- The preflight no longer checks a mode.

### Task 3: Python-only soak contract

**Files:** `operations/tiktok_soak.py`, `tests/operations/test_tiktok_soak.py`.

The changes:

- An observation's `activity_mode` is `Literal["python"]`.
- Remove the `legacy_fallback` route, count, rate, policy maximum and blocker.
- No soak evidence exists yet: the single soak runs at the end, per ADR 0001.

### Task 4: Image, compose, CI, Makefile and deploy

**Files:**
- `Dockerfile` and `compose.stage1.local.yml`
- `compose.stage1.cdp-smoke.yml`, `docker/start-legacy-cdp` and `docker/test-cdp-offline.sh` (all three deleted)
- `.github/workflows/container-image.yml`, `Makefile` and `scripts/ops/deploy-stage1.sh`
- `python/pyproject.toml` and `uv.lock` (the `scout-runtime` extra goes)
- `.gitattributes` and `.env.stage1.local.example`
- the deployment tests

The changes:

- `deploy-stage1.sh` brings the stack up with `--remove-orphans`.

### Task 5: Contract, dashboard and the `scout/` tree

The changes:

- Regenerate `python/openapi.json` and `dashboard/src/api/generated/control-plane.ts`; the `legacy_source` skip reason goes.
- Drop `skip.legacy_source` from both locales.
- Delete `scout/`.

### Task 6: Docs and records

The changes:

- Update the living operator docs:
  - `docs/operations/stage1-local-docker.md`;
  - `docs/CONFIGURATION.md`;
  - `docs/python-control-plane.md`;
  - the status lines in `BLUEPRINT.md`.
- Add a `CHANGELOG.md` entry with the next steps.

**Verification:**

- `make test` (full Python suite), `make lint`, the dashboard tests and build;
- `docker compose ... config --quiet` on the deploy file set;
- `actionlint`.
