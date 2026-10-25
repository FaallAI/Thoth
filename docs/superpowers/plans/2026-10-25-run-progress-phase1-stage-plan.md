# Run progress, phase 1: the stage plan. Implementation plan

Date: 2026-10-25.
- **Spec:** `docs/superpowers/specs/2026-10-25-run-progress-contract-design.md`, G1 (approved).
- **Roadmap:** "Dashboard redesign track", step 2.
- **Checkpoint:** `.superpowers/sdd/2026-10-25-run-progress-phase1/progress.md`.

## Goal

`WorkflowSummary.stages` carries the run's **whole plan from the first snapshot**. Each stage has:
- its real status: `queued`, `running`, `waiting`, `completed`, `failed`, `cancelled` or `skipped`;
- `started_at` and `finished_at`;
- for skipped stages, a `skip_reason` code.

**Out of this phase:** steps, `current_step`, estimates, the inbox, render frames (phases 2-5), and any dashboard restyle.

## Ground truth (read before coding)

**Where `_summary` stands:** `workflows/source_investigation.py` `_summary()` builds one hard-coded `source` stage whose status mirrors `self._status`. It is the only place a `StageSummary` is built. `application/workflow_runs.py` builds an expired run's summary with `stages=[]`.

**Where transitions happen:**
- Every stage start and finish already goes through `_record_event(EventKind.STAGE_STARTED | STAGE_COMPLETED, stage=StageProgress(name=...))`, with the names `source`, `attribution`, `footage` and `assembly`.
- The approval uses `APPROVAL_REQUIRED` and the approve, reject and cancel branches in `_run`.
- Failures set `self._failure` with `failed_stage` (`source`, `attribution`, `assembly`); then come `_transition(FAILED)` and `WORKFLOW_FAILED`.
- **Cancellation:** `_transition(CANCELLED)`.
- **Legacy Scout path:** `self._report_from_legacy`; the chain does nothing.

**Flags:** `SourceInvestigationWorkflowInput.intent`, `attribute_source`, `assemble_content`, `build_footage` (all default `False` for old histories).

**`produce_video` runs the chain after approval only when** `workflow.patched(PRODUCE_CHAIN_PATCH)`.

**Domain:** `domain/models.py` `StageSummary`:
- `id` pattern `^(validation|source|assets|narration|render|review|delivery)$`;
- status `Literal["queued","running","completed","waiting","failed","cancelled"]`.

`StrictModel` is strict, so stored JSON summaries are read with `model_validate_json` (ISO strings).

**Contract:**
- `python/scripts/export_openapi.py` writes `python/openapi.json`;
- `dashboard` `bun run generate:control-plane-types` writes `src/api/generated/control-plane.ts`;
- `dashboard/src/components/WorkflowMonitor.tsx` reads `stages` for the progress bar and the list.

## Design decisions (fixed; ask before changing)

**D1. Plan by intent and flags.**

| Stage id | Label | In the plan when | Otherwise |
|---|---|---|---|
| `source` | Fetch the source | always | — |
| `approval` | Your review | `intent == "produce_video"` | not in the plan |
| `attribution` | Find the original | always | `skipped`, `attribution_off` when `attribute_source` is false |
| `footage` | Collect footage | always | `skipped`, `footage_off` unless `assemble_content and build_footage` |
| `assembly` | Build the content set | always | `skipped`, `assembly_off` when `assemble_content` is false |

**D2. Runtime skips.**
- The legacy source path skips every chain stage still `queued` with `legacy_source`.
- A reject skips them with `approval_rejected`.
- A `produce_video` approve without `PRODUCE_CHAIN_PATCH` (an old history) skips them with `not_in_this_version`.
- After a failure, the failed stage is `failed` and the later queued stages are `skipped` with `run_failed`.
- After a cancel, the running or waiting stage is `cancelled` and the later queued stages are `skipped` with `run_cancelled`.

**D3. State and events.**
- A `StagePlan` holds the stages, kept in a new pure module `workflows/stage_plan.py`, with no Temporal import beyond what the sandbox passes through.
- Its methods: `start(id, at)`, `wait(id, at)`, `complete(id, at)`, `fail(id, at)`, `cancel_open(at)`, `skip_queued(reason)`, `snapshot() -> list[StageSummary]`.
- **The workflow drives it:**
  - from `_record_event` for STAGE_STARTED and STAGE_COMPLETED (name → id);
  - at APPROVAL_REQUIRED (`wait`);
  - at approve (`complete`), reject, legacy, failure (`failed_stage` → id) and cancel;
  - always with `workflow.now()`.
- **No new Temporal command is issued, so replay is unaffected and no patch is needed.**

**D4. Domain changes**, all backward compatible:
- **`StageSummary.id`:** the pattern adds `approval|attribution|footage|assembly`, and the old ids are kept.
- **Status:** adds `skipped`.
- **New fields:** `started_at: datetime | None = None`, `finished_at: datetime | None = None` (RFC 3339 validated like `WorkflowSummary`), and `skip_reason: Literal[...] | None = None` with the D2 codes plus the D1 off codes.
- **Defaults** keep every stored summary valid and keep the fields optional in the generated TypeScript (use `default_factory` where needed: openapi-typescript v7 makes fields with a plain default required).

**D5. `progress`.** `source` keeps `progress = 1.0` once its report artifact exists. The other stages report `None` (steps arrive in phase 2).

**D6. Dashboard (minimal, no restyle).**
- `WorkflowMonitor` counts progress over the stages that are not `skipped`.
- It shows `skipped` stages muted, with the label "Skipped".
- It keeps the server label.
- Only the generated types and this component change.

## Tasks (test first; one commit per task; English commit subjects, one line)

1. **Domain.**
   - **Tests** (`tests/domain/...`):
     - the new ids and `skipped` validate;
     - an old stored summary JSON (no new fields) validates;
     - bad timestamps are refused.
   - **Change:** implement D4.
2. **StagePlan.**
   - **Tests** (`tests/workflows/test_stage_plan.py`, pure):
     - the plans for `identify_original` and `produce_video` with every flag combination;
     - every transition in D2 and D3, including the timestamps and idempotent completes.
   - **Change:** implement `workflows/stage_plan.py`.
3. **Workflow wiring.**
   - **Tests** (`tests/workflows/test_source_investigation.py`, with the existing fakes):
     - (a) a `produce_video` run with the chain on: the query while awaiting approval shows `source` completed (with times), `approval` waiting and the chain queued; after approve and finish, everything is completed with ordered timestamps;
     - (b) reject → the chain is `skipped`/`approval_rejected`;
     - (c) cancel during footage → footage `cancelled`, assembly `skipped`/`run_cancelled`;
     - (d) an assembly failure → assembly `failed`;
     - (e) `identify_original` with the flags off → three `skipped` with the off codes and no `approval` stage;
     - (f) the legacy path → `legacy_source`.
   - **Change:** wire D3 into `_run`, `_attribute`, `_footage`, `_assemble` and the approval branch; `_summary()` returns `self._plan.snapshot()`.
4. **Replay safety.**
   - **Fixture:**
     - from `origin/master` *before* this branch, in a separate worktree, record the full histories of a `produce_video` run (chain on, approved) and an `identify_original` run with the existing test fakes;
     - save them as JSON fixtures under `tests/workflows/fixtures/`;
     - document in the test how they were made.
   - **Test:** replay both with the new code (`Replayer`), and add one more replay of each.
   - **Existing replay tests** (pre-metering, pre-chain) stay green.
5. **Contract.**
   - Run `python python/scripts/export_openapi.py`, then `bun run generate:control-plane-types` in `dashboard/`.
   - Commit both generated files. Check that the diff only adds the new ids, the status and the optional fields.
6. **Dashboard (D6).**
   - **Tests:** `WorkflowMonitor.test.tsx` covers skipped stages excluded from progress and shown muted.
   - **Change:** the minimal change.
7. **Docs.**
   - `CHANGELOG.md` entry: what, why, the evidence and the next steps.
   - Update `docs/ROADMAP.md` "Dashboard redesign track" step 2 to "Done (branch …), awaiting review". Change that cell only.

## Verification (record the evidence in the checkpoint)

- **Python, from WSL:**
  - `bash scripts/dev/pytest-wsl.sh tests/domain tests/workflows tests/application` while iterating;
  - then the full `bash scripts/dev/pytest-wsl.sh`;
  - `make lint`.
- **Dashboard:** `bun test` for the touched files, then the dashboard suite; `bun run build` (or the existing typecheck script).
- **Determinism:** the Task 4 replay tests pass. A mutation check proves they bite: temporarily add a command to the wiring (`await workflow.sleep(1)` right after the source stage completes in `_run`), see both replays fail with a nondeterminism error, then revert.
- **No contract drift beyond D4** in `openapi.json` and the generated TypeScript.

## Constraints

- Rust is frozen: no `cargo update` and no `build_cuda.bat`.
- No live requests to any platform or provider; offline tests only.
- Keep `#[serde(default)]` equivalents, meaning new fields have defaults.
- Every change degrades gracefully.
- **Repository artifacts in English:**
  - one-line commit subjects through a single `git commit -m`;
  - no body, no trailer, no `Co-Authored-By`.
- Never stage `.superpowers/`, `graphify-out/`, `.serena/` or `design/` (use `git add -f` only for `docs/superpowers/...`).
- Work in a worktree on branch `feat/run-progress-stage-plan` from `origin/master`.
