# Workflow Reports in PostgreSQL — Design

Status: approved in conversation by the operator, 2026-10-16. Follow-up 4 of Stage 5b.

## Goal

The control plane's JSON reports live in PostgreSQL as their single source of truth. No
activity writes or reads a report file on the artifact volume any more. Media (videos, card
PNGs, footage clips, render outputs) stays on disk.

## Decisions (operator, 2026-10-16)

1. **Single source of truth.** Reports are stored only in PostgreSQL; the report files are no
   longer written.
2. **Old reports are imported once.** An operator command imports the report files already on
   disk; afterwards code reads only the database. The files are never deleted by code.
3. **One table keyed by the existing location** (approach A). The stored content is the exact
   bytes, so every `ArtifactRef` already recorded in Temporal history (location, checksum,
   size) stays valid after the import.
4. **Media to S3 is a separate sub-project** with its own spec, written after this one.

## Scope

Report kinds, and every place that writes or reads one today:

| Location | Kind | Writer | Readers |
|---|---|---|---|
| `reports/<workflow_id>/source-report.json` | `source_report` | `activities/source_investigation.py` | `activities/source_attribution.py`, `activities/footage.py`, `activities/content_assembly.py`, API artifact download |
| `reports/<candidate_id>/source-report.json` (the original's report) | `original_source_report` | `activities/source_attribution.py` | `activities/content_assembly.py`, `activities/footage.py`, API |
| `reports/<workflow_id>/source-attribution.json` | `source_attribution` | `activities/source_attribution.py` | `activities/content_assembly.py`, `activities/footage.py`, API |
| `reports/<workflow_id>/content-set.json` | `content_set` | `activities/content_assembly.py` | API |
| `legacy-scout/<workflow_id>/source-report.json` | `source_report` | `activities/legacy_scout.py` (Bun subprocess output) | API |

Out of scope:
- Media files of any kind (S3 is the next spec).
- Footage state, which is already in PostgreSQL (`footage_*`, migration 0010).
- Render bundles and render metadata under `work/` and `renders/` (`LocalArtifactRoot`).
- Operations tooling that writes fixtures or captures (`operations/*_capture.py`, fixture
  writers, controlled fallback, parity). These are operator tools, not pipeline storage;
  `operations/tiktok_parity.py` already takes the report payload from its caller.
- Typed per-kind tables, and deleting old report files.
- The Rust server and the dashboard: neither reads a report file directly. The dashboard
  reads reports only through the API artifact route.

## Storage

Editor migration `0011_workflow_reports.sql`, applied by Alembic revision `0011` exactly like
0010 (`execute_sql_file`):

```sql
CREATE TABLE workflow_reports (
    location    text PRIMARY KEY,
    workflow_id text NOT NULL,
    kind        text NOT NULL,
    content     text NOT NULL,
    body        jsonb GENERATED ALWAYS AS (replace(content, '\u0000', '')::jsonb) STORED,
    sha256      char(64) NOT NULL,
    size_bytes  integer NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX workflow_reports_workflow ON workflow_reports (workflow_id, kind);
```

- `location` is the same relative string the `ArtifactRef` carries. It is validated with the
  same rule as `ArtifactRef.location` (relative, no `..`, no scheme) before it is stored.
- `workflow_id` is the first segment's folder id: the workflow id, or the candidate id for an
  original's report.
- `content` holds the exact UTF-8 JSON text that was produced, so `sha256` and `size_bytes`
  match the `ArtifactRef` checksum and size.
- `body` exists only for querying. PostgreSQL `jsonb` rejects the `\u0000` escape that scraped
  text can contain, so the generated expression drops that escape; `content` is never altered.
- `kind` is the `ArtifactRef.kind` of the report: one of `source_report`,
  `original_source_report`, `source_attribution`, `content_set` (`REPORT_KINDS`).

ORM model `WorkflowReportRow` on the shared declarative `Base`
(`infrastructure/source_account_models.py`), mapping every column except `body` (a
PostgreSQL-only generated column), so the in-memory SQLite test pattern keeps working.

`infrastructure/report_store.py` — `ReportStore`, synchronous like `FootageStore`; callers use
`asyncio.to_thread`:
- `ReportStore.connect(url)` and `ReportStore(engine)`.
- `put(location, kind, content: bytes) -> None` — upsert by `location` (a Temporal retry
  rewrites the same row), sets `sha256`, `size_bytes`, `updated_at`. Content that is not valid
  UTF-8 JSON is refused with `ReportInvalid`.
- `get(location) -> bytes | None` — the exact stored bytes, or `None` when absent.
- Any database error (unreachable, timeout, SQL failure) raises `ReportStoreUnavailable`.
  It is never turned into `None`: a database outage is not a missing report.
- `insert_missing(location, kind, content) -> bool` — for the import only: inserts when absent,
  never overwrites, returns whether it inserted.

## Writers

Each writer replaces its file write with `store.put` and builds the same `ArtifactRef` it
builds today (same location, checksum over the same bytes, same size).

- `ReportStoreUnavailable` on a write:
  - `source_investigation` returns its existing typed failure `artifact_persistence_failed`
    (retryable), as it does for a failed file write today;
  - `source_attribution` and `content_assembly` let it propagate as a retryable activity
    error, so Temporal retries the activity. Today a failed file write there degrades
    (attribution `unresolved`, assembly `artifact_write_failed`); with a database that is
    down, degrading would silently drop a result that a retry recovers, so these two
    change on purpose.
- The `.part` file handling and `_cleanup_after_persistence_failure` for reports go away.
- **Legacy Scout**: the Bun subprocess still needs an output path. It writes to a scratch file
  under `temp/legacy-scout/<workflow_id>/`; the activity reads it, `put`s it under the
  unchanged location `legacy-scout/<workflow_id>/source-report.json`, and deletes the scratch
  file. A missing scratch file keeps today's `legacy_scout_report_missing`.

## Readers

Attribution, footage, and assembly call `store.get(location)` where they read the file today.
- An absent row, invalid JSON, or a schema mismatch behaves exactly as a missing or
  unreadable file does today: attribution `unresolved` ("no stage 3 report"), footage
  `unavailable`, assembly `source_report_missing`, and the optional attribution and original
  reads in assembly and footage treated as absent.
- `ReportStoreUnavailable` propagates as a retryable activity error in every reader. It never
  takes the "no report" path.
- No reader falls back to the file.

## API artifact download

`GET /workflows/{workflow_id}/artifacts/{artifact_id}` keeps its ownership check. For an
artifact whose kind is a report kind it returns the stored bytes (`Response`, the artifact's
`media_type`, the same `filename` as today); an absent row is `ArtifactNotFound`. Every other
artifact is served from disk as today.

## Configuration

`THOTH_EDITOR_DATABASE_URL` becomes required for the worker and the API. When it is missing,
startup fails with a clear error naming the variable (required dependencies fail loud; no
silent degradation). Both compose stacks already set it; the CI non-live smoke already starts
`editor-postgresql`. The worker's activities share one `ReportStore` built at startup.

## Import of existing reports

`thoth-control reports import --artifact-root <path>` (operator gate; it needs the database
URL like `editor migrate`):

- Scans `reports/*/source-report.json`, `reports/*/source-attribution.json`,
  `reports/*/content-set.json`, and `legacy-scout/*/source-report.json`. Nothing else.
- Skips links and anything outside the root.
- Checks only that the bytes are valid UTF-8 JSON: old reports may carry older schema
  versions, and they are stored as they are.
- `insert_missing` for each file: an existing row is never overwritten, so a rerun is a no-op.
- Prints counts only: `imported=<n> present=<n> invalid=<n>` (no paths, no content).
- Deletes nothing.

## Operations

- **Back up PostgreSQL and the artifact volume together.** After this change a workflow's
  reports live in PostgreSQL while its media stays on the volume. Restoring one without the
  other leaves reports without media, or media without reports.
- **Every workflow depends on the editor PostgreSQL.** If it is down, every stage that writes
  or reads a report fails with a retryable error; the report path no longer works without it.
- **The import is part of the deploy, never a manual afterthought** (operator, 2026-10-16:
  "pastikan impor setelah deploy"). The deploy script runs, in order and stopping on the
  first failure:
  1. `editor migrate` (applies 0011);
  2. stop the old `worker` service — no old code can write a report file after this point;
     Temporal keeps the pending activity tasks queued, nothing is lost;
  3. `reports import` with the new image — every report file the old code ever wrote is now
     in the database;
  4. a check that step 3 printed `invalid=0`; otherwise the deploy stops here with the old
     worker stopped and the operator decides (restart the old worker, or fix and re-run);
  5. `up` (the new image starts the workers and the API).
  The deploy runbook and the deploy script in use both carry these steps. Because the old
  worker is stopped before the import, no new worker can ever miss a report written before
  the deploy. The import stays idempotent, so re-running the deploy is safe.
- Image rollback: an older image writes files again and cannot read reports written to the
  database. Avoid rolling back while workflows are in flight.

These go in the runbook (`docs/` deploy notes) as well as the CHANGELOG entry.

## Testing

All offline.
- `ReportStore` on in-memory SQLite: put/get round trip of exact bytes, upsert on retry,
  `insert_missing` never overwrites, invalid JSON refused.
- PostgreSQL migration test (the existing disposable-Postgres migration test pattern): 0011
  applies; `body` is generated; a report containing `\u0000` inside a string is stored, its
  `content` is unchanged, and its `body` is queryable.
- Each writer: the `ArtifactRef` checksum and size equal the stored row's; no report file is
  written to the artifact root; `ReportStoreUnavailable` yields `artifact_persistence_failed`
  in source investigation and a raised retryable error in attribution and assembly.
- Each reader: reads from the store; an absent row yields today's missing-report behavior;
  `ReportStoreUnavailable` raises instead of taking that path; no file read is attempted.
- Legacy Scout: scratch file is stored under the unchanged location and removed.
- API: a report artifact is served from the store with exact bytes; a media artifact is
  still served from disk; another owner's workflow is still refused.
- Import: imports files, skips present rows, counts invalid JSON, rerun is a no-op, ignores
  other files and links.
- Startup: missing `THOTH_EDITOR_DATABASE_URL` fails the worker and the API with the named
  error.

## Review focus

1. A Temporal retry of a writer after a successful `put` — same row, same `ArtifactRef`.
2. A report with `\u0000` in a caption — stored, checksum intact.
3. A workflow started before the deploy and resumed after it — the old worker was stopped
   before the import, so every report it wrote is in the database and the reader finds it.
4. The database unavailable mid-run — retryable failure, nothing half-written.
5. The API serving a report artifact of a workflow owned by someone else — refused.
