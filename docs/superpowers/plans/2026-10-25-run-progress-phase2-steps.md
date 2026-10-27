# Run progress, phase 2: steps. Implementation plan

Date: 2026-10-25.
- **Spec:** `docs/superpowers/specs/2026-10-25-run-progress-contract-design.md`, G2, G3, §3, §4 and §5 (approved).
- **Roadmap:** "Dashboard redesign track", step 3.
- **Checkpoint:** `.superpowers/sdd/2026-10-25-run-progress-phase2/progress.md`.
- **Branch:** `feat/run-progress-steps`, stacked on `feat/run-progress-stage-plan` (`8a7a3af`, phase 1, reviewed GO).
  - **The operator's ruling (2026-10-25):** the track's steps share one set of gates. Phase 1 stays local, and push, PR, merge and deploy happen later for the stack.

## Goal

Activities record **steps** into a Postgres table `workflow_steps`. The API serves them through `GET /workflows/{id}/steps`, and the snapshot shows each running or waiting stage's `current_step`.

**Out of this phase:**
- emitting the catalogue codes from the real acquirers, attribution, footage and assembly (phase 3);
- estimates and the inbox (phase 4);
- render frames (phase 5);
- any dashboard UI change (step 7). The generated types do change.

## Ground truth (read before coding)

**The pattern to copy is metering.**
- `metering.py` has a ContextVar scope, a process-wide sink (`install`), and `record`/`record_sync`, which never fail the work (`warn` on a sink error, nothing recorded without a sink).
- `activities/meter_scope.py` has `MeterScopeInterceptor`, installed in `worker.py` (`interceptors=[MeterScopeInterceptor(client)]`).
- `worker.run_worker` installs `UsageStore.connect(THOTH_EDITOR_DATABASE_URL)`. The worker refuses to start without the editor database.
- **Store pattern:** `infrastructure/usage_store.py` (SQLAlchemy ORM, synchronous, `connect()` with a small pool; async callers use `asyncio.to_thread`). Its ORM rows sit in `infrastructure/usage_models.py`. They share `Base` and `UtcDateTime` from `infrastructure/source_account_models.py`.
- **Store tests:** SQLite via `tests.sqlite_support.sqlite_engine` (see `tests/infrastructure/test_usage_store.py`).

**Activity names → stages:**

| Activity | Stage |
|---|---|
| `inspect_source_candidates` | `source` |
| `attribute_source` | `attribution` |
| `build_footage` | `footage` |
| `assemble_content` | `assembly` |

`inspect_legacy_scout`, `record_workflow_completed` and `run_prompt_proposal` get no step scope.

**Migrations:**
- each one is a SQL file `python/migrations/editor/00NN_*.sql` plus an Alembic revision `python/migrations/editor/alembic/versions/00NN_*.py` that calls `execute_sql_file(__file__)`;
- the latest is `0018` (`down_revision = "0017"`);
- covered by `tests/operations/test_editor_migrations.py` and the Postgres suite `tests/operations/test_editor_migrations_postgres.py` (`make test-postgres`).

**API:**
- `api/routes/workflows.py` `GET /workflows/{workflow_id}` → `WorkflowRunService.get` (`application/workflow_runs.py`). That method queries Temporal, settles the stored summary, and falls back to the stored row when the history expired.
- **Ownership:** `run.owned_by(actor)`.
- `WorkflowNotFound` maps to 404 in `api/app.py`.
- `app.state.usage_store` is built in `api/app.py` from `THOTH_EDITOR_DATABASE_URL`.

**Contract:**
- `python/scripts/export_openapi.py` → `python/openapi.json`;
- `dashboard` `generate:control-plane-types`.
- **Known issue F2:** `dashboard/package.json` pins `typescript ~7.0.2`, which `openapi-typescript` 7.13 cannot use. Phase 1 generated the types with the main checkout's `node_modules` (TypeScript 6). Do the same, and do not change the pin here.

## Design decisions (fixed; ask before changing)

**D1. Domain** (`domain/models.py`):
- **`StepKind`** = `Literal["info", "progress", "wait", "done", "warning", "error"]`.
- **`WorkflowStep(StrictModel)`:**
  - `seq: int` (≥ 1);
  - `stage`: pattern `^(source|attribution|footage|assembly)$`;
  - `attempt: int` (≥ 1);
  - `at: datetime` (RFC 3339, validated like `StageSummary`);
  - `kind: StepKind`;
  - `code`: pattern `^(source|attribution|footage|assembly)\.[a-z_]+$`;
  - `n` and `total: int | None` (≥ 0);
  - `wait_until: datetime | None`;
  - `params: dict[str, str | int] | None`.
- **`WorkflowStepPage(StrictModel)`:** `steps: list[WorkflowStep]`.
- **`StageSummary.current_step`:** `WorkflowStep | None = None`, filled by the API only.
- **All new fields are optional with defaults.**

**D2. Catalogue** (`progress.py`):
- **`CATALOGUE: dict[str, StepKind]`** holds exactly the spec §5 codes, written as `stage.name`.
  - `source.page_gap` is `wait`.
  - `source.gate_covered` and `source.login_wall` are `warning`.
  - Every other code is `info`.
- **The kind recorded:**
  - `wait` when `wait_until` is given;
  - else `warning` when the catalogue says so;
  - else `progress` when `n` is given;
  - else `info`.
- `done` and `error` stay valid in the schema but are unused in this phase.
- **Unknown code:** the step is dropped with a `warn`. A code whose stage differs from the scope's stage is also dropped with a `warn`.

**D3. Recorder** (`progress.py`, mirroring `metering.py`):
- **`StepScope`:** a frozen dataclass with `workflow_id`, `stage`, `attempt`, and a per-scope coalescing state (`field(default_factory=dict, compare=False)`, so nothing leaks globally).
- **Functions:**
  - `install(sink)`, `current_scope()`, `scoped(scope)`;
  - `step_sync(code, *, n=None, total=None, wait_until=None, params=None)`;
  - `async step(...)`, which goes through `asyncio.to_thread` like `metering.record`.
- **Never raises:**
  - without a sink or a scope, nothing is recorded (`debug`);
  - a sink error is a `warn` that names only the code.
- **Params whitelist:**
  - allowed keys: `verdict`, `platform`, `count`;
  - values are an `int`, or a `str` matching `^[a-z0-9_.-]{1,40}$`;
  - any other key or value drops the whole `params` (`warn`), and the step is still recorded.
  - This keeps URLs, cookies, tokens and raw exception text out.
- **Coalescing:**
  - a `progress` step with the same code as the last *written* one in this scope, less than 1.0 s later (`time.monotonic`, held in a module attribute tests can patch), is dropped;
  - it is never dropped when `n == total`.
- **Timestamp:** `at` is `datetime.now(UTC)` from the recorder.

**D4. Interceptor** (`activities/progress_scope.py`):
- `ProgressScopeInterceptor` maps the activity type (`activity.info().activity_type`) through `STAGE_OF_ACTIVITY` (the table above).
- It sets `StepScope(workflow_id, stage, attempt=activity.info().attempt)` around `execute_activity`. Other activities run without a scope.
- It does no network call.
- `worker.py` adds it next to `MeterScopeInterceptor`, and installs the step sink beside the usage sink.

**D5. Storage:**
- **Migration `0019_workflow_steps`** (SQL plus Alembic, `down_revision = "0018"`), exactly spec §4:
  - **columns:** `workflow_id TEXT NOT NULL` with **no foreign key** (spec §4, "why"), `seq BIGSERIAL PRIMARY KEY`, `attempt INT NOT NULL`, `stage TEXT NOT NULL CHECK (...)`, `at TIMESTAMPTZ NOT NULL`, `kind TEXT NOT NULL CHECK (...)`, `code TEXT NOT NULL`, `n INT`, `total INT`, `wait_until TIMESTAMPTZ`, `params JSONB`;
  - **index** `workflow_steps_workflow (workflow_id, seq)`.
  - Spec §4 also lists the `workflow_runs.acknowledged_at` column and the `render_jobs` frame columns. **Those belong to phases 4 and 5; leave them out.**
- **ORM:** `WorkflowStepRow` in `infrastructure/step_models.py`, on the shared `Base`.
- **`StepStore`** in `infrastructure/step_store.py`, synchronous like `UsageStore`:
  - `connect(url)`;
  - `append(scope, record)`;
  - `page(workflow_id, after, limit) -> list[WorkflowStep]` (ordered by `seq`);
  - `current_steps(workflow_id) -> dict[str, WorkflowStep]`: for each stage, the latest step of that stage's highest attempt.
- **Retention:** grep for code that deletes `workflow_runs` rows. If there is any, delete that run's steps in the same place and test it. If there is none, write "none found" in the checkpoint.

**D6. API:**
- **Endpoint:** `GET /workflows/{workflow_id}/steps?after=0&limit=200` (`after ≥ 0`, `1 ≤ limit ≤ 500`) → `WorkflowStepPage`, through a new `WorkflowRunService.steps(workflow_id, *, actor, after, limit)`.
- **Authorization:** from the `workflow_runs` row (`self._runs.get` plus `owned_by`). There is no Temporal query, because the dashboard polls this every second. A missing or foreign row raises `WorkflowNotFound` (404).
- **No run store or no step store:** an empty page (graceful degradation).
- **`current_step`:**
  - `WorkflowRunService.get` fills it on the stages whose status is `running` or `waiting`, with one `current_steps` call;
  - it does this **after** `settle`, so stored summaries never hold it;
  - a step-store error is a `warn`, and the summary is returned without it.
- **Store wiring:** `api/app.py` builds the step store beside `usage_store` (same URL) and passes it to `WorkflowRunService`.

**D7. Contract:** regenerate `openapi.json` and the TypeScript types. The diff may only add `WorkflowStep`, `WorkflowStepPage`, `StageSummary.current_step` and the new path.

**D8. The workflow is untouched.** `workflows/source_investigation.py` does not change, so the replay tests from phase 1 and earlier must stay green unchanged.

## Tasks (test first; one commit per task; one-line English subjects)

1. **Domain (D1).** Tests in `tests/domain/test_workflow_step.py`:
   - valid steps;
   - a bad code, stage or kind is refused;
   - bad timestamps are refused;
   - an old `StageSummary` without `current_step` still validates.
2. **Recorder and catalogue (D2, D3).** Tests in `tests/test_progress.py` with a fake sink:
   - kind derivation;
   - an unknown code is dropped;
   - a stage mismatch is dropped;
   - the params whitelist (a URL value is dropped, an int is kept);
   - coalescing with the patched clock, including `n == total` always written;
   - no scope and no sink record nothing;
   - a sink exception becomes a `warn` and `step()` returns normally;
   - two scopes do not share coalescing state.
3. **Interceptor and worker wiring (D4).** Tests in `tests/activities/test_progress_scope.py`, in the style of `test_meter_scope.py`:
   - each mapped activity type sets the right stage and attempt;
   - an unmapped one has no scope;
   - a `progress.step` inside the activity reaches the sink with that scope.

   Also test that the worker's interceptor list contains both interceptors.
4. **Migration, ORM and store (D5).**
   - **Migration:** extend `tests/operations/test_editor_migrations.py` for the 0019 pair, and add a 0019 case to the Postgres suite.
   - **Store** (`tests/infrastructure/test_step_store.py`, SQLite):
     - `append` and `page` order and `after` and `limit`;
     - `current_steps` picks the highest attempt, then the latest seq;
     - the params JSON round-trips.
5. **Service and API (D6).** Tests:
   - steps page happy path;
   - a foreign actor gets 404, and a missing run gets 404;
   - no store gives an empty page;
   - `limit` and `after` bounds give 422;
   - `current_step` is filled only on running or waiting stages and is absent from the summary passed to `settle`;
   - a step-store error still returns the summary.
6. **Contract (D7):** regenerate both files, audit the diff, and commit.
7. **Docs:** a `CHANGELOG.md` entry, and only the step 3 status cell of the `docs/ROADMAP.md` "Dashboard redesign track". Change no other line.

## Verification (record the evidence in the checkpoint)

- **Python, from WSL in the worktree:**
  - while iterating: `bash scripts/dev/pytest-wsl.sh tests/domain tests/activities tests/infrastructure tests/application tests/api tests/operations tests/test_progress.py`;
  - then the full `bash scripts/dev/pytest-wsl.sh`, then `make lint`.
- **Postgres:**
  - run `make test-postgres`; Docker is inside WSL.
  - If it cannot run here, say so explicitly with the error, and do not claim the 0019 migration was applied on Postgres.
- **Dashboard:** the full `bun test` and `bun run build`. Only the generated types change.
- **Replay:** the phase 1 fixture replays and the older replay tests pass unchanged (D8).
- **Contract:** the `git diff` summary of `openapi.json` and the TypeScript types shows D7 only.

## Constraints

- **No live requests or deploy:** none to platforms or providers, and no deploy.
- **Rust is frozen:** no `cargo update` and no `build_cuda.bat`.
- **Commits:** one-line English subjects through a single `git commit -m`. No body, trailer or `Co-Authored-By`.
- **Staging:** never stage `.superpowers/`, `graphify-out/`, `.serena/` or `design/`. Use `git add -f` only for `docs/superpowers/...`.
- **Logs and steps** never carry secrets, URLs or raw exception text.
- **Line endings:** keep LF; edit through the editor tools.
