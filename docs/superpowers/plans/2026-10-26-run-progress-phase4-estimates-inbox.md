# Run progress, phase 4: estimates and inbox. Implementation plan

Date: 2026-10-26.

| | |
|---|---|
| Spec | `docs/superpowers/specs/2026-10-25-run-progress-contract-design.md`, G4 (estimates) and G5 (inbox) (approved; operator decision 2: the inbox shows accounts in cooldown or unhealthy, for platform admins only) |
| Design | `docs/DESIGN.md` §7.3 (timing and estimates) and §7.6 (live surfaces) |
| Roadmap | "Dashboard redesign track", step 5 |
| Checkpoint | `.superpowers/sdd/2026-10-26-run-progress-phase4/progress.md` |
| Branch | `feat/run-progress-estimates-inbox`, stacked on `feat/run-progress-instrumentation` (`8da3c2d`, phase 3 reviewed GO, pushed as a backup branch, not merged) |

The track shares one set of operator gates.

## Goal

1. **The snapshot carries `estimate_seconds_remaining`** for a running run.
2. **`GET /inbox`** lists:
   - the caller's runs awaiting approval;
   - the caller's failed runs not yet acknowledged;
   - for platform admins, source accounts in cooldown or expired.
3. **`POST /workflows/{id}/acknowledge`** clears a failed run from the inbox.

**Out of scope:**
- render frames (phase 5);
- any dashboard UI (step 7); the generated types do change;
- the workflow code: no file under `workflows/` changes.

## Ground truth (read before coding)

**Run ownership.** Runs are scoped by `(actor_type, actor_id)`; `StoredRun.owned_by` is in `domain/workflow_runs.py`.
- The run list's store query (`infrastructure/workflow_run_store.py` `page`) filters on both.
- The workspace of a run is `auth/models.py` `actor_workspace_id(actor_id)`.
- **"The workspace's runs" in the spec means this actor scope.** There is no `workspace_id` column on `workflow_runs`.

**Row freshness.** `workflow_runs.status` is refreshed lazily.
- `WorkflowRunService.page` settles at most `SETTLE_LIMIT` rows whose status is in `UNSETTLED` (`queued | running | awaiting_approval | unknown`), each with `SETTLE_TIMEOUT_SECONDS`, through `self._settle`.
- `get` settles the opened run.
- An `awaiting_approval` run can therefore still read `running` in its row until something settles it.

**Stored summaries.**
- `workflow_runs.summary` (JSON) holds the `WorkflowSummary`.
- Since phase 1, its `stages` carry `started_at` and `finished_at`. Older summaries do not, and their stages are ignored.
- Phase 2 fills `current_step` in `get` after `settle`, through `_with_current_steps`. The estimate follows the same rule: it is filled after `settle` and never stored.

**Source accounts.**
- `infrastructure/source_account_store.py` `accounts() -> list[AccountView]`, with `id`, `platform`, `label`, `status` and `cooldown_until`.
- **Statuses** (migration 0008): `healthy`, `cooldown`, `expired`, `disabled`.
- **Platform admin:** `auth/models.py` `is_platform_admin(principal)` plus `"admin" in principal.scopes`. That is the `api/dependencies.py` `platform_actor` rule.
- **The API store:** `api/app.py` `_source_account_store` / the `source_account_store` parameter.

**Migrations.** The latest is `0019_workflow_steps`. The SQL file plus Alembic pair pattern is the same as in phase 2. `0012` created `workflow_runs` with the indexes `workflow_runs_project` and `workflow_runs_unsettled`.

**Contract generation.** F2 is fixed on this stack: `bun run generate:control-plane-types` works with TypeScript 7. If the worktree has no `dashboard/node_modules`, run `bun install --frozen-lockfile` in `dashboard/` (Bun 1.4.4).

## Design decisions (fixed; ask before changing)

### D1. Estimate (pure module `application/estimates.py`, no I/O)

**Inputs:**
- the run's `WorkflowSummary`;
- the actor's last ≤ 20 **succeeded** stored summaries for the same platform;
- `now`.

**Rules:**
- **Medians:** for each stage id, the median duration (`finished_at − started_at`, in seconds) over the stored summaries whose stage is `completed` with both timestamps.
- **Too few runs:** fewer than 5 succeeded summaries means `None`; DESIGN says the UI then reads "a few minutes".
- **Defaults:** when a stage has no median, use the spec defaults: `source` 120, `attribution` 60, `footage` 240, `assembly` 60.
- **Remaining time, by stage status:**

| Status | Remaining |
|---|---|
| `queued` | the stage's median |
| `running` | `max(median − elapsed, wait_remaining, 0)`, where `wait_remaining = wait_until − now` when `current_step.kind == "wait"` |
| `completed`, `skipped`, `failed`, `cancelled` | 0 |

- **No estimate:** the result is `None` when the run is not `running` or `queued`. `awaiting_approval` gets `None` too, because a person is the wait, not the machine. The `approval` stage never counts.
- **Result:** the total remaining, rounded to whole seconds.

### D2. Estimate wiring

- **Domain:** `WorkflowSummary.estimate_seconds_remaining: int | None = None` (≥ 0; filled by the API only).
- **Store:** `WorkflowRunStore.recent_succeeded(actor, platform, limit=20) -> list[WorkflowSummary]` (status `succeeded`, a summary present, newest `updated_at` first).
- **Service:** `WorkflowRunService.get` fills the estimate **after** `_with_current_steps`, so the running stage's `current_step` is known. It never goes into `settle`.
- **Cache:** the medians input is cached per `(actor_type, actor_id, platform)` for 60 s in the service, because the dashboard polls `get` often. Mark it with a `ponytail:` comment naming the ceiling (per-process, stale ≤ 60 s).
- **Failure:** a store error is a `warn`, and the summary is returned without the estimate.

### D3. Acknowledging failed runs

- **Migration `0020_workflow_run_acknowledged`** (SQL plus Alembic, `down_revision = "0019"`):
  - `ALTER TABLE workflow_runs ADD COLUMN acknowledged_at TIMESTAMPTZ;`
  - `CREATE INDEX workflow_runs_unacknowledged_failures ON workflow_runs (actor_type, actor_id, updated_at DESC) WHERE status = 'failed' AND acknowledged_at IS NULL;`
- **Model:** ORM column and `StoredRun.acknowledged_at: datetime | None = None`.
- **Endpoint:** `POST /workflows/{workflow_id}/acknowledge` → 204.
  - A missing or foreign run → `WorkflowNotFound` (404).
  - A run whose row status is not `failed` → 409 `run_not_failed`. Settle the row first if it is unsettled, so a just-failed run can be acknowledged.
  - It is idempotent and keeps the first `acknowledged_at`.
- **Opening a run** never acknowledges it (spec G5).

### D4. Inbox (`GET /inbox` → `Inbox`)

- **`Inbox`:** `approvals: list[InboxRun]`, `failures: list[InboxRun]`, `accounts: list[InboxAccount]`.
- **`InboxRun`:** `workflow_id`, `project_id`, `display_url`, `platform`, `status`, `updated_at`, `failure_code: str | None` (from the stored summary's `failure.code`).
- **`InboxAccount`:** `account_id`, `platform`, `label`, `status`, `cooldown_until`.
- **Approvals:**
  - first settle the actor's unsettled rows, newest first, at most `SETTLE_LIMIT`, with the existing `_settle` (same timeout and degradation);
  - then take rows with status `awaiting_approval`, newest first, at most 20.
- **Failures:** status `failed` and `acknowledged_at IS NULL`, newest first, at most 20.
- **Accounts:**
  - only when the principal is a platform admin with the `admin` scope;
  - accounts whose `status` is `cooldown` or `expired`, or whose `cooldown_until > now`;
  - `disabled` is deliberate, so it is excluded;
  - otherwise the list is `[]`.
  - Never include cookies, proxy data or cookie names.
- **No run store:** an empty inbox (graceful degradation).
- **No account store:** accounts are `[]`.

### D5. Contract

Regenerate `openapi.json` and the TypeScript types. The diff may only add:
- `WorkflowSummary.estimate_seconds_remaining`;
- `Inbox`, `InboxRun`, `InboxAccount`;
- the two new paths.

### D6. The workflow is untouched

`git diff 8da3c2d -- python/src/thoth_control_plane/workflows/` must be empty.

## Tasks (test first; one commit per task; one-line English subjects)

1. **Estimate math (D1).** Pure unit tests in `tests/application/test_estimates.py`:
   - fewer than 5 runs gives `None`;
   - medians with an odd and an even count;
   - the defaults for a stage that never ran;
   - a running stage with elapsed time beyond its median gives 0;
   - a wait step extends the remaining time;
   - `awaiting_approval` and terminal runs give `None`;
   - old summaries without timestamps are ignored.
2. **Estimate wiring (D2).** Store tests (SQLite) for `recent_succeeded`, then service tests:
   - the estimate is filled after `current_step`;
   - it is not present in what `settle` receives;
   - the cache hits within 60 s;
   - a store error still returns the summary.
3. **Migration and acknowledge (D3).**
   - **Migration:** the pair test and the Postgres suite (`make test-postgres`), including the partial index.
   - **Store and service tests:** 204, idempotence, 404 for a foreign run, 409 for a non-failed run, settle-then-acknowledge.
4. **Inbox (D4).** Service and route tests:
   - approvals after settling a stale `running` row that is really awaiting approval;
   - unacknowledged failures only;
   - accounts only for an admin with the scope;
   - `disabled` is excluded;
   - no secret fields in the payload;
   - empty without stores.
5. **Contract (D5).** Regenerate, audit the diff, and commit.
6. **Docs.** A `CHANGELOG.md` entry, and only the step 5 status cell of `docs/ROADMAP.md` "Dashboard redesign track".

## Verification (record the evidence in the checkpoint)

- **Python, from WSL in the worktree:**
  - while iterating, `bash scripts/dev/pytest-wsl.sh tests/application tests/api tests/infrastructure tests/domain tests/operations tests/workflows`;
  - then the full `bash scripts/dev/pytest-wsl.sh`, then `make lint`.
- **Postgres:** `make test-postgres`. If it cannot run, give the exact error and do not claim the migration was applied.
- **Dashboard:** `bun test` and `bun run build`. Only the generated types change. With Bun 1.4.4, `GuidedStudio.responsive.test.tsx` "keeps one preview mounted across every viewport" is a known pre-existing flake: rerun its file alone and report it by name.
- **D6:** the empty workflow diff, and the phase 1 fixture replays plus the older replay tests pass.
- **Contract:** the diff summary shows D5 only.

## Constraints

- **Offline only:** no requests to any platform or provider, and no deploy.
- **Rust is frozen:** no `cargo update`, no `build_cuda.bat`.
- **Commits:** one-line English subjects through a single `git commit -m`. No body, no trailer, no `Co-Authored-By`.
- **Never stage** `.superpowers/`, `graphify-out/`, `.serena/` or `design/`. Use `git add -f` only for `docs/superpowers/...`.
- **Never print secrets.** The inbox exposes no account secrets.
- **Line endings:** keep LF; edit through the editor tools.
- **Event loop:** never call a blocking store method on an event loop. Use `asyncio.to_thread` as the existing services do (the phase 3 R1 lesson).

## Hard stops

- **Stop and ask** if:
  - D1-D6 cannot be implemented as written;
  - the workflow code would need a change;
  - the contract diff goes beyond D5.
- Stop after Task 6 with local commits.
- **Do not push, open a PR, merge or deploy.**
- Do not start phase 5.
