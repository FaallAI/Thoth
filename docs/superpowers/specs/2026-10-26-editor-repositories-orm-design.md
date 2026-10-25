# Editor repositories on the SQLAlchemy ORM: design and plan

Date: 2026-10-26. Status: approved by the operator on 2026-10-26 ("kerjakan terkait ini sekalian sekarang").

**Rule it completes:** the 2026-09-25 direction. New persistence uses the full SQLAlchemy ORM plus Alembic, and converting the existing psycopg repositories needs its own spec. This is that spec.

## Release

This work is its own branch from `master`, with its own PR and deploy, so it can be traced and rolled back on its own (operator, 2026-10-26).
- It is **not** part of the run-progress stack.
- Whichever lands second adapts. The plan is for this to land first, then the run-progress stack rebases onto it.
- At that rebase, phase 5's four `render_jobs` frame columns move into the ORM model. The schema-parity test catches a miss.

## Scope

The seven repositories that still use raw psycopg, all from the editor and Creator Studio era:

| Repository | Lines | Postgres features in use |
|---|---|---|
| `editor_asset_repository` | 210 | keyset paging, `= ANY` |
| `studio_review_repository` | 315 | advisory lock, `FOR UPDATE` |
| `prompt_repository` | 270 | advisory lock, `FOR UPDATE` |
| `editor_repository` | 383 | advisory lock, `FOR UPDATE`, JSONB |
| `studio_import_repository` | 493 | advisory lock, `FOR UPDATE`, JSONB |
| `render_job_repository` | 512 | advisory lock, `FOR UPDATE`, JSONB, the active-slot unique index |
| `prompt_proposal_repository` | 981 | advisory locks, `FOR UPDATE` |

**Out of scope:**
- any schema change. The ORM mirrors the shipped SQL, and the migrations stay as they are;
- any change to the application, API or contract.

## Design

**D1. Same pattern as the existing ORM stores.**
- Synchronous ORM sessions, called from the async methods through `asyncio.to_thread`. This is the pattern of `UsageStore`, `WorkflowRunStore` and `StepStore`.
- Every public method keeps its exact async signature and its typed errors, so no caller changes.

**D2. One pool per database URL.**
- Today every psycopg call opens a new connection.
- The converted repositories share one engine per URL (`infrastructure/editor_database.py`, cached), with `pool_pre_ping`, a small pool and `hide_parameters`, like the other stores.

**D3. Models mirror the migrations.**
- The ORM rows (`infrastructure/editor_models.py`) declare the same tables, columns, keys and types as migrations 0001-0007 and 0017.
- JSONB columns use `JSON().with_variant(JSONB(), "postgresql")`.
- **A Postgres parity test** compares every mapped table's columns, types and nullability with the migrated schema, so a model can never drift from the SQL.

**D4. Postgres semantics are preserved.**
- **Advisory transaction locks:** `select(func.pg_advisory_xact_lock(...))` with the same namespace and key derivation as today.
- **Row locks:** `.with_for_update()`.
- **Constraint mapping:** a constraint violation maps to the same typed error by SQLSTATE and constraint name, read from `IntegrityError.orig`.
- On SQLite the advisory lock is a no-op, so logic tests run anywhere. Lock and constraint behavior is proven on Postgres.

**D5. Errors stay redacted.** Each repository raises its own persistence error with no driver text, exactly as now.

**D6. Tests describe behavior, not SQL text.**
- The fake-cursor tests that assert on SQL strings are replaced by behavior tests:
  - SQLite (`tests.sqlite_support`) for the logic;
  - Postgres (`THOTH_TEST_EDITOR_DATABASE_URL`, `make test-postgres`, required in CI) for locks, unique indexes, JSONB and schema parity.
- Every behavior the old tests pinned is kept, unless it was only the SQL text.

**D7. Known difference.**
- Cancelling the awaiting coroutine no longer aborts an in-flight statement; the thread finishes its transaction.
- That is already true of every ORM store here, and each operation is one short transaction.

## Plan (one commit per repository, test first)

1. The shared engine, the models for all seven areas, and the Postgres parity test.
2. `editor_asset_repository`.
3. `studio_review_repository`.
4. `prompt_repository`.
5. `editor_repository`.
6. `studio_import_repository`.
7. `render_job_repository`.
8. `prompt_proposal_repository`.
9. Remove the dead psycopg helpers.
   - **Check:** `rg "psycopg" python/src/thoth_control_plane` finds only the migration runner, if it still needs psycopg. Anything else is listed in the report.
   - Then the docs: CHANGELOG, plus the roadmap row.

**After each step:**
- the repository's tests (SQLite and Postgres);
- the full Python suite;
- `make lint`;
- `make test-postgres`.

## Verification

- **Python:** the full suite and `make lint`.
- **Postgres:** `make test-postgres`, including the schema-parity test and the lock and constraint tests.
- **Contract:** `git diff --exit-code python/openapi.json`. There is no contract change.
