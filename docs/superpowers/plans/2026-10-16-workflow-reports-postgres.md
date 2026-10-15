# Workflow Reports in PostgreSQL Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the control plane's JSON reports (source report, original's report, attribution, content set) from files on the artifact volume into one PostgreSQL table that is their single source of truth, with a one-time import of the old files built into the deploy.

**Architecture:** A `workflow_reports` table (editor migration 0011) keyed by the report's existing artifact location stores the exact JSON bytes plus a generated `jsonb` copy for querying. A synchronous `ReportStore` (SQLAlchemy ORM, like `FootageStore`) replaces every report file write and read in the activities and the API download route. An operator CLI imports the old files; the deploy script stops the old worker, imports, then starts the new image.

**Tech Stack:** Python 3.12, SQLAlchemy 2 ORM, Alembic (hand-written revision running a shipped SQL file), psycopg 3, Temporal activities, FastAPI, Typer, pytest, GitHub Actions service containers.

**Spec:** `docs/superpowers/specs/2026-10-16-workflow-reports-postgres-design.md` (operator-approved 2026-10-16).

## Prerequisites

- PRs #9 (cleanup) and #10 (Makefile) are merged, and this branch (`feat/workflow-reports-postgres`) is rebased on `master`. The Makefile targets and `scripts/dev/pytest-wsl.sh` / `scripts/ops/deploy-stage1.sh` come from #10.
- Every "Run:" command runs from WSL at the repository root:
  `wsl -e bash -lc 'cd /mnt/c/Users/mfr/Documents/MyTools/CLIPPER && make test T=<path>'`.
  python/.venv is a Windows venv and cannot run tests.

## Global Constraints

- Reports live only in PostgreSQL; no activity writes or reads a report file after this change. Media stays on disk.
- `ArtifactRef` values do not change: same `location`, checksum over the same bytes, same `size_bytes`.
- Report kinds: `source_report`, `original_source_report`, `source_attribution`, `content_set`.
- A database error is never treated as a missing report (`ReportStoreUnavailable` is never turned into `None`).
- New persistence uses SQLAlchemy ORM models and sessions, not raw psycopg; the schema change is an Alembic revision that runs a shipped `.sql` file (0011), like 0010.
- Postgres-only behavior (the generated `jsonb` column, the `\u0000` case) is proven on a real PostgreSQL 16.4 — in CI and locally through `make test-postgres` — never inferred from SQLite. A skipped Postgres test is a failure wherever `THOTH_REQUIRE_POSTGRES_TESTS=1`.
- Logs carry counts and codes only; never report content, captions, or paths of report rows.
- Tests are offline (the conftest guard blocks non-loopback). No new dependency.
- Commits: exactly one `git commit -m "<subject>"`, no body, no trailer, no AI attribution. Never stage `.superpowers/`, `design/`, `graphify-out/`, `.serena/`, or the `.codegraph` database.
- Chat to the operator in Indonesian; every repository artifact in English.

## Review Focus

1. A Temporal retry of a writer after a successful `put` — same row, same `ArtifactRef` (Task 2, Task 3).
2. A report containing `\u0000` inside a string — stored, `content` unchanged, `body` queryable, checksum intact (Task 1, Postgres test).
3. The database down while a report is read or written — retryable failure, never the "no report" path (Tasks 2–4).
4. The API serving a report artifact of a workflow the caller does not own — still refused (Task 5).
5. The import meeting a link, a non-JSON file, or a file outside the four names — skipped or counted invalid, never imported, never fatal (Task 6).

## File Structure

| File | Responsibility |
|---|---|
| `python/migrations/editor/0011_workflow_reports.sql` (new) | The table, its generated `body`, its index |
| `python/migrations/editor/alembic/versions/0011_workflow_reports.py` (new) | Alembic revision that runs the SQL file |
| `python/src/thoth_control_plane/infrastructure/report_models.py` (new) | ORM row `WorkflowReportRow` (no `body`) |
| `python/src/thoth_control_plane/infrastructure/report_store.py` (new) | `ReportStore`, `Reports` protocol, errors, `REPORT_KINDS`, `read_report`, `connect_reports` |
| `python/src/thoth_control_plane/activities/source_investigation.py` | Writes the source report through the store |
| `python/src/thoth_control_plane/activities/source_attribution.py` | Reads the source report, writes attribution + original's report through the store |
| `python/src/thoth_control_plane/activities/content_assembly.py` | Reads reports and writes the content set through the store; shared `_attribution`/`_original` readers |
| `python/src/thoth_control_plane/activities/footage.py` | Reads reports through the store |
| `python/src/thoth_control_plane/activities/legacy_scout.py` | Scratch file → store → scratch removed |
| `python/src/thoth_control_plane/worker.py` | Requires the editor DB; one shared store for every activity |
| `python/src/thoth_control_plane/api/app.py`, `api/routes/workflows.py` | Report artifacts served from the store |
| `python/src/thoth_control_plane/operations/report_import.py` (new), `cli.py` | `thoth-control reports import` |
| `scripts/dev/pytest-postgres.sh` (new), `Makefile` | Throwaway PostgreSQL for the Postgres tests |
| `.github/workflows/container-image.yml` | PostgreSQL service + required Postgres tests in the quality job |
| `scripts/ops/deploy-stage1.sh` | migrate → stop worker → import → check → up |
| `docs/RUNNING.md`, `CHANGELOG.md` | Runbook steps and records |

---

### Task 1: The report table, the store, and real-Postgres proof

**Files:**
- Create: `python/migrations/editor/0011_workflow_reports.sql`
- Create: `python/migrations/editor/alembic/versions/0011_workflow_reports.py`
- Create: `python/src/thoth_control_plane/infrastructure/report_models.py`
- Create: `python/src/thoth_control_plane/infrastructure/report_store.py`
- Create: `python/tests/infrastructure/test_report_store.py`
- Create: `scripts/dev/pytest-postgres.sh`
- Modify: `python/tests/operations/test_editor_migrations.py` (0011 SQL assertions; the chain test already walks every revision)
- Modify: `python/tests/operations/test_editor_migrations_postgres.py` (counts, required mode, 0011 behavior)
- Modify: `python/tests/conftest.py` (a `report_store` fixture)
- Modify: `Makefile` (`test-postgres` target)
- Modify: `.github/workflows/container-image.yml` (quality job: PostgreSQL service, required Postgres tests)

**Interfaces:**
- Produces (used by every later task):
  - `REPORT_KINDS: frozenset[str]`
  - `class ReportInvalid(ValueError)`, `class ReportStoreUnavailable(RuntimeError)`
  - `class Reports(Protocol)`: `put(location: str, kind: str, content: bytes) -> None`; `get(location: str) -> bytes | None`
  - `class ReportStore` (implements `Reports`): `ReportStore(engine)`, `ReportStore.connect(url: str)`, `put`, `get`, `insert_missing(location, kind, content) -> bool`
  - `async def read_report(reports: Reports, location: str, model: type[M]) -> M | None`
  - `def connect_reports(settings: Settings) -> ReportStore` — raises `SettingsValidationError("editor_database_missing")` when `THOTH_EDITOR_DATABASE_URL` is unset
  - pytest fixture `report_store` (in-memory SQLite `ReportStore`)

- [ ] **Step 1: Write the failing store tests**

`python/tests/infrastructure/test_report_store.py`:

```python
"""The report store on in-memory SQLite (the footage store's test pattern)."""

from __future__ import annotations

import asyncio
from hashlib import sha256

import pytest
from pydantic import BaseModel
from sqlalchemy import select

from thoth_control_plane.infrastructure.report_models import WorkflowReportRow
from thoth_control_plane.infrastructure.report_store import (
    ReportInvalid,
    ReportStore,
    ReportStoreUnavailable,
    read_report,
)

LOCATION = "reports/wf_test/source-report.json"
CONTENT = b'{\n  "schema_version": 3,\n  "caption": "a\\u0000b"\n}'


class Doc(BaseModel):
    schema_version: int


def test_put_then_get_returns_the_exact_bytes(report_store: ReportStore) -> None:
    report_store.put(LOCATION, "source_report", CONTENT)
    assert report_store.get(LOCATION) == CONTENT


def test_a_row_records_checksum_size_kind_and_folder(report_store: ReportStore) -> None:
    report_store.put(LOCATION, "source_report", CONTENT)
    with report_store._sessions() as session:
        row = session.scalar(select(WorkflowReportRow))
    assert row is not None
    assert row.workflow_id == "wf_test"
    assert row.kind == "source_report"
    assert row.sha256 == sha256(CONTENT).hexdigest()
    assert row.size_bytes == len(CONTENT)


def test_a_second_put_replaces_the_row(report_store: ReportStore) -> None:
    report_store.put(LOCATION, "source_report", CONTENT)
    report_store.put(LOCATION, "source_report", b'{"schema_version": 4}')
    assert report_store.get(LOCATION) == b'{"schema_version": 4}'


def test_an_absent_location_is_none(report_store: ReportStore) -> None:
    assert report_store.get("reports/wf_none/source-report.json") is None


def test_insert_missing_never_overwrites(report_store: ReportStore) -> None:
    assert report_store.insert_missing(LOCATION, "source_report", CONTENT) is True
    assert report_store.insert_missing(LOCATION, "source_report", b'{"x": 1}') is False
    assert report_store.get(LOCATION) == CONTENT


@pytest.mark.parametrize(
    ("location", "kind", "content"),
    [
        (LOCATION, "source_report", b"not json"),
        (LOCATION, "source_report", b"\xff\xfe"),
        (LOCATION, "media", CONTENT),
        ("/etc/passwd", "source_report", CONTENT),
        ("reports/../x/source-report.json", "source_report", CONTENT),
        ("reports/wf_test/clip.mp4", "source_report", CONTENT),
    ],
)
def test_invalid_input_is_refused(
    report_store: ReportStore, location: str, kind: str, content: bytes
) -> None:
    with pytest.raises(ReportInvalid):
        report_store.put(location, kind, content)


def test_a_database_error_is_unavailable_never_none() -> None:
    from sqlalchemy import create_engine

    broken = ReportStore(create_engine("sqlite:////nonexistent/dir/db.sqlite"))
    with pytest.raises(ReportStoreUnavailable):
        broken.get(LOCATION)
    with pytest.raises(ReportStoreUnavailable):
        broken.put(LOCATION, "source_report", CONTENT)


def test_read_report_validates_and_treats_a_bad_document_as_absent(
    report_store: ReportStore,
) -> None:
    report_store.put(LOCATION, "source_report", CONTENT)
    report_store.put("reports/wf_bad/source-report.json", "source_report", b'{"x": 1}')
    assert asyncio.run(read_report(report_store, LOCATION, Doc)) == Doc(schema_version=3)
    assert asyncio.run(read_report(report_store, "reports/wf_bad/source-report.json", Doc)) is None
    assert asyncio.run(read_report(report_store, "reports/wf_no/source-report.json", Doc)) is None
```

Add to `python/tests/conftest.py` (with its imports at the top of the file):

```python
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from thoth_control_plane.infrastructure.report_store import ReportStore
from thoth_control_plane.infrastructure.source_account_models import Base


@pytest.fixture
def report_store() -> ReportStore:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    return ReportStore(engine)
```

- [ ] **Step 2: Run them to see them fail**

Run: `make test T=tests/infrastructure/test_report_store.py`
Expected: FAIL — `ModuleNotFoundError: thoth_control_plane.infrastructure.report_models`.

- [ ] **Step 3: Write the migration, the ORM row, and the store**

`python/migrations/editor/0011_workflow_reports.sql`:

```sql
-- Workflow reports (spec 2026-10-16): the single store of the control plane's JSON reports,
-- keyed by the artifact location the ArtifactRef already carries. `content` is the exact JSON
-- text (checksums match); `body` is a queryable copy. jsonb refuses the \u0000 escape that
-- scraped text can contain, so `body` drops it; `content` is never altered.

CREATE TABLE workflow_reports (
    location TEXT PRIMARY KEY CHECK (char_length(location) BETWEEN 1 AND 1024),
    workflow_id TEXT NOT NULL CHECK (char_length(workflow_id) BETWEEN 1 AND 128),
    kind TEXT NOT NULL CHECK (
        kind IN ('source_report', 'original_source_report', 'source_attribution', 'content_set')
    ),
    content TEXT NOT NULL,
    body JSONB GENERATED ALWAYS AS (replace(content, '\u0000', '')::jsonb) STORED,
    sha256 CHAR(64) NOT NULL,
    size_bytes INTEGER NOT NULL CHECK (size_bytes >= 0),
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX workflow_reports_workflow ON workflow_reports (workflow_id, kind);
```

`python/migrations/editor/alembic/versions/0011_workflow_reports.py`:

```python
"""Apply the shipped 0011_workflow_reports.sql verbatim."""

from thoth_control_plane.operations.editor_migrations import execute_sql_file

revision = "0011"
down_revision = "0010"


def upgrade() -> None:
    execute_sql_file(__file__)
```

`python/src/thoth_control_plane/infrastructure/report_models.py`:

```python
"""SQLAlchemy ORM mapping of the workflow report table (editor migration 0011).

`body` is a PostgreSQL generated column and is not mapped, so SQLite tests keep working.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from thoth_control_plane.infrastructure.source_account_models import Base, UtcDateTime


class WorkflowReportRow(Base):
    __tablename__ = "workflow_reports"

    location: Mapped[str] = mapped_column(String, primary_key=True)
    workflow_id: Mapped[str] = mapped_column(String)
    kind: Mapped[str] = mapped_column(String)
    content: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime)
```

`python/src/thoth_control_plane/infrastructure/report_store.py`:

```python
"""Workflow reports in PostgreSQL (editor migration 0011): their single source of truth.

Synchronous like the footage store; callers wrap calls in `asyncio.to_thread` (`read_report`
does it for reads). A database error is `ReportStoreUnavailable`, never an absent report.
"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Callable
from datetime import UTC, datetime
from hashlib import sha256
from typing import TYPE_CHECKING, Protocol, TypeVar

from pydantic import BaseModel, ValidationError
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from thoth_control_plane.infrastructure.report_models import WorkflowReportRow

if TYPE_CHECKING:
    from thoth_control_plane.config import Settings

REPORT_KINDS = frozenset(
    {"source_report", "original_source_report", "source_attribution", "content_set"}
)
#: `reports/<id>/<name>.json` or `legacy-scout/<id>/<name>.json`, one safe segment each.
_LOCATION = re.compile(r"^(reports|legacy-scout)/([A-Za-z][A-Za-z0-9_-]{0,127})/[a-z][a-z-]*\.json$")

M = TypeVar("M", bound=BaseModel)


class ReportInvalid(ValueError):
    """The location, kind, or content cannot be a stored report."""


class ReportStoreUnavailable(RuntimeError):
    """The database could not be reached or refused the statement."""


class Reports(Protocol):
    def put(self, location: str, kind: str, content: bytes) -> None: ...

    def get(self, location: str) -> bytes | None: ...


def _checked(location: str, kind: str, content: bytes) -> tuple[str, str]:
    """Return (folder id, text) or raise `ReportInvalid`."""
    match = _LOCATION.fullmatch(location)
    if match is None or kind not in REPORT_KINDS:
        raise ReportInvalid("report_location_or_kind_invalid")
    try:
        text = content.decode("utf-8")
        json.loads(text)
    except (UnicodeDecodeError, ValueError) as error:
        raise ReportInvalid("report_content_invalid") from error
    return match.group(2), text


class ReportStore:
    def __init__(
        self, engine: Engine, clock: Callable[[], datetime] = lambda: datetime.now(UTC)
    ) -> None:
        self._sessions = sessionmaker(engine, expire_on_commit=False)
        self._clock = clock

    @classmethod
    def connect(cls, database_url: str) -> ReportStore:
        url = make_url(database_url).set(drivername="postgresql+psycopg")
        return cls(create_engine(url, pool_pre_ping=True, pool_size=2, max_overflow=2))

    def put(self, location: str, kind: str, content: bytes) -> None:
        """Store or replace one report (a Temporal retry rewrites the same row)."""
        folder, text = _checked(location, kind, content)
        now = self._clock()
        try:
            with self._sessions.begin() as session:
                row = session.get(WorkflowReportRow, location)
                if row is None:
                    session.add(self._row(location, folder, kind, text, content, now))
                    return
                row.kind = kind
                row.content = text
                row.sha256 = sha256(content).hexdigest()
                row.size_bytes = len(content)
                row.updated_at = now
        except SQLAlchemyError as error:
            raise ReportStoreUnavailable("report_store_unavailable") from error

    def get(self, location: str) -> bytes | None:
        try:
            with self._sessions() as session:
                row = session.get(WorkflowReportRow, location)
        except SQLAlchemyError as error:
            raise ReportStoreUnavailable("report_store_unavailable") from error
        return None if row is None else row.content.encode("utf-8")

    def insert_missing(self, location: str, kind: str, content: bytes) -> bool:
        """Import only: insert when absent, never overwrite. True when it inserted."""
        folder, text = _checked(location, kind, content)
        now = self._clock()
        try:
            with self._sessions.begin() as session:
                if session.get(WorkflowReportRow, location) is not None:
                    return False
                session.add(self._row(location, folder, kind, text, content, now))
                return True
        except SQLAlchemyError as error:
            raise ReportStoreUnavailable("report_store_unavailable") from error

    @staticmethod
    def _row(
        location: str, folder: str, kind: str, text: str, content: bytes, now: datetime
    ) -> WorkflowReportRow:
        return WorkflowReportRow(
            location=location,
            workflow_id=folder,
            kind=kind,
            content=text,
            sha256=sha256(content).hexdigest(),
            size_bytes=len(content),
            created_at=now,
            updated_at=now,
        )


async def read_report(reports: Reports, location: str, model: type[M]) -> M | None:
    """The report, or None when it is absent or no longer matches `model`.

    `ReportStoreUnavailable` propagates: a database outage is not a missing report.
    """
    raw = await asyncio.to_thread(reports.get, location)
    if raw is None:
        return None
    try:
        return model.model_validate_json(raw)
    except ValidationError:
        return None


def connect_reports(settings: Settings) -> ReportStore:
    """The production store; the editor database is required (spec 2026-10-16)."""
    from thoth_control_plane.config import SettingsValidationError

    if settings.THOTH_EDITOR_DATABASE_URL is None:
        raise SettingsValidationError("editor_database_missing")
    return ReportStore.connect(settings.THOTH_EDITOR_DATABASE_URL.get_secret_value())
```

- [ ] **Step 4: Run the store tests**

Run: `make test T=tests/infrastructure/test_report_store.py`
Expected: PASS (all).

- [ ] **Step 5: Pin the shipped SQL in the offline migration test**

Append to `python/tests/operations/test_editor_migrations.py`:

```python
def test_workflow_reports_keep_exact_content_and_a_queryable_body() -> None:
    sql = " ".join(migration("0011_workflow_reports.sql").split())

    assert "CREATE TABLE workflow_reports" in sql
    assert "location TEXT PRIMARY KEY" in sql
    assert "content TEXT NOT NULL" in sql
    assert "body JSONB GENERATED ALWAYS AS (replace(content, '\\u0000', '')::jsonb) STORED" in sql
    assert (
        "kind IN ('source_report', 'original_source_report', 'source_attribution', 'content_set')"
        in sql
    )
    assert "CREATE INDEX workflow_reports_workflow ON workflow_reports (workflow_id, kind)" in sql
```

Run: `make test T=tests/operations/test_editor_migrations.py`
Expected: PASS (the existing chain test now walks 0001–0011).

- [ ] **Step 6: Make the Postgres tests current, required where asked, and cover 0011**

In `python/tests/operations/test_editor_migrations_postgres.py`:

1. Replace the `pytestmark` block with:

```python
#: CI and `make test-postgres` set this: there a skipped Postgres test is a failure.
REQUIRED = os.environ.get("THOTH_REQUIRE_POSTGRES_TESTS") == "1"

if REQUIRED and not DATABASE_URL:
    raise RuntimeError("THOTH_REQUIRE_POSTGRES_TESTS=1 but THOTH_TEST_EDITOR_DATABASE_URL is unset")

pytestmark = pytest.mark.skipif(
    not DATABASE_URL, reason="THOTH_TEST_EDITOR_DATABASE_URL points at a disposable Postgres"
)
```

2. Fix the stale counts: `== 8` becomes `== 11`; in the pre-Alembic adoption test `== 2` becomes `== 5`; add `"workflow_reports"` to the fresh-database table set.

3. Append:

```python
def test_a_report_with_a_nul_escape_is_stored_exactly_and_queryable() -> None:
    from hashlib import sha256

    from thoth_control_plane.infrastructure.report_store import ReportStore

    apply_editor_migrations(DATABASE_URL, MIGRATIONS)
    content = b'{"caption": "a\\u0000b", "schema_version": 3}'
    store = ReportStore.connect(DATABASE_URL)
    store.put("reports/wf_nul/source-report.json", "source_report", content)

    assert store.get("reports/wf_nul/source-report.json") == content
    with psycopg.connect(DATABASE_URL) as connection:
        row = connection.execute(
            "SELECT sha256, body->>'caption', (body->>'schema_version')::int "
            "FROM workflow_reports WHERE location = %s",
            ("reports/wf_nul/source-report.json",),
        ).fetchone()
    assert row == (sha256(content).hexdigest(), "ab", 3)


def test_a_report_kind_outside_the_four_is_refused_by_the_table() -> None:
    apply_editor_migrations(DATABASE_URL, MIGRATIONS)
    with psycopg.connect(DATABASE_URL) as connection, pytest.raises(psycopg.errors.CheckViolation):
        connection.execute(
            "INSERT INTO workflow_reports (location, workflow_id, kind, content, sha256, "
            "size_bytes, created_at, updated_at) VALUES "
            "('reports/wf_x/a.json', 'wf_x', 'media', '{}', repeat('0', 64), 2, now(), now())"
        )
```

- [ ] **Step 7: A throwaway PostgreSQL for local runs**

`scripts/dev/pytest-postgres.sh`:

```bash
#!/usr/bin/env bash
# Run the Postgres-backed tests against a throwaway PostgreSQL 16.4 (the stack's own image),
# removed afterwards. A skipped Postgres test fails here (THOTH_REQUIRE_POSTGRES_TESTS=1).
#
#     bash scripts/dev/pytest-postgres.sh [pytest args...]
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
image=postgres:16.4-bookworm@sha256:e62fbf9d3e2b49816a32c400ed2dba83e3b361e6833e624024309c35d334b412
name="thoth-test-postgres-$$"
port=55432

docker run -d --rm --name "$name" -e POSTGRES_PASSWORD=thoth -p "127.0.0.1:$port:5432" "$image" >/dev/null
trap 'docker rm -f "$name" >/dev/null 2>&1 || true' EXIT
for _ in $(seq 1 60); do
    docker exec "$name" pg_isready -U postgres >/dev/null 2>&1 && break
    sleep 1
done
docker exec "$name" pg_isready -U postgres >/dev/null

[ "$#" -gt 0 ] || set -- tests/operations/test_editor_migrations_postgres.py
THOTH_TEST_EDITOR_DATABASE_URL="postgresql://postgres:thoth@127.0.0.1:$port/postgres" \
THOTH_REQUIRE_POSTGRES_TESTS=1 \
    bash "$root/scripts/dev/pytest-wsl.sh" "$@"
```

Makefile — add `test-postgres` to `.PHONY` and this target after `check`:

```make
test-postgres: ## Postgres-backed tests on a throwaway PostgreSQL 16.4 (a skip is a failure)
	bash scripts/dev/pytest-postgres.sh
```

Run: `make test-postgres`
Expected: PASS — 5 tests, 0 skipped (the three existing ones with their corrected counts, plus the two new ones).

- [ ] **Step 8: Make CI run them against a real PostgreSQL**

In `.github/workflows/container-image.yml`, job `quality`:

```yaml
  quality:
    name: Offline quality gates
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:16.4-bookworm@sha256:e62fbf9d3e2b49816a32c400ed2dba83e3b361e6833e624024309c35d334b412
        env:
          POSTGRES_PASSWORD: thoth
        ports:
          - 127.0.0.1:5432:5432
        options: >-
          --health-cmd "pg_isready -U postgres"
          --health-interval 2s
          --health-timeout 5s
          --health-retries 30
```

and in the step `Run Python non-live tests`, add to `env`:

```yaml
          THOTH_TEST_EDITOR_DATABASE_URL: postgresql://postgres:thoth@127.0.0.1:5432/postgres
          THOTH_REQUIRE_POSTGRES_TESTS: "1"
```

Run locally: `actionlint .github/workflows/container-image.yml` (if installed; otherwise
`python -c "import yaml,sys; yaml.safe_load(open('.github/workflows/container-image.yml'))"`).
Expected: no errors.

- [ ] **Step 9: Commit**

```bash
git add python/migrations/editor/0011_workflow_reports.sql python/migrations/editor/alembic/versions/0011_workflow_reports.py python/src/thoth_control_plane/infrastructure/report_models.py python/src/thoth_control_plane/infrastructure/report_store.py python/tests/infrastructure/test_report_store.py python/tests/conftest.py python/tests/operations/test_editor_migrations.py python/tests/operations/test_editor_migrations_postgres.py scripts/dev/pytest-postgres.sh Makefile .github/workflows/container-image.yml
git commit -m "feat(reports): store workflow reports in PostgreSQL"
```

---

### Task 2: Source investigation writes its report to the store; the worker requires the database

**Files:**
- Modify: `python/src/thoth_control_plane/activities/source_investigation.py` (`_run` persistence block around lines 309–360; `build_source_investigation_activity`; `_cleanup_after_persistence_failure`)
- Modify: `python/src/thoth_control_plane/worker.py` (`check_media_tools`, `build_source_investigation_worker`, `run_worker`)
- Test: `python/tests/activities/test_source_investigation.py`, `python/tests/workflows/test_source_investigation.py` (the registered-root test near line 688), `python/tests/test_worker.py` (or wherever `check_media_tools` is tested — find with `grep -rn check_media_tools python/tests`)

**Interfaces:**
- Consumes: `Reports`, `ReportStoreUnavailable`, `connect_reports`, fixture `report_store` (Task 1).
- Produces: `build_source_investigation_activity(settings, *, runner=None, capability=None, reports: Reports | None = None)`; `build_source_investigation_worker(client, settings, *, runner=None, capability=None, reports: Reports | None = None)`. When `reports` is None both call `connect_reports(settings)` once. Later tasks add `reports=` to the other three builders and the worker passes the same instance to all four.

Behavior:
- The report bytes are produced exactly as today (`report.model_dump_json(indent=2, exclude_none=False).encode("utf-8")`) and stored with `await asyncio.to_thread(reports.put, location.as_posix(), "source_report", content)`.
- `ReportStoreUnavailable` → `_cleanup_after_persistence_failure(report, artifact_root)` (media and cards only; the `part_path` parameter and its unlink are removed) and the existing failure `artifact_persistence_failed` (retryable). The `asyncio.CancelledError` branch keeps cleaning media and re-raises.
- No `.part` file, no `report_path.parent.mkdir`, no report file anywhere.
- `check_media_tools` starts with: `if settings.THOTH_EDITOR_DATABASE_URL is None: raise SettingsValidationError("editor_database_missing")` (reports are written by every worker).

- [ ] **Step 1: Write the failing tests** (in `tests/activities/test_source_investigation.py`, following the file's existing runner fakes and its existing successful-run test, which you copy and adapt):

```python
async def test_the_report_is_stored_not_written(tmp_path, report_store) -> None:
    activity = build_source_investigation_activity(
        _settings(tmp_path), runner=_successful_runner(), capability=_capability(),
        reports=report_store,
    )
    result = await activity(_input("wf_store"))

    stored = report_store.get("reports/wf_store/source-report.json")
    assert stored is not None
    assert result.report.location == "reports/wf_store/source-report.json"
    assert result.report.checksum == f"sha256:{sha256(stored).hexdigest()}"
    assert result.report.size_bytes == len(stored)
    assert not (tmp_path / "reports" / "wf_store" / "source-report.json").exists()


async def test_a_retry_rewrites_the_same_row(tmp_path, report_store) -> None:
    activity = build_source_investigation_activity(
        _settings(tmp_path), runner=_successful_runner(), capability=_capability(),
        reports=report_store,
    )
    first = await activity(_input("wf_retry"))
    second = await activity(_input("wf_retry"))
    assert first.report == second.report


class _DownReports:
    def put(self, location: str, kind: str, content: bytes) -> None:
        raise ReportStoreUnavailable("report_store_unavailable")

    def get(self, location: str) -> bytes | None:
        raise ReportStoreUnavailable("report_store_unavailable")


async def test_a_database_outage_is_a_retryable_persistence_failure(tmp_path) -> None:
    activity = build_source_investigation_activity(
        _settings(tmp_path), runner=_successful_runner(), capability=_capability(),
        reports=_DownReports(),
    )
    result = await activity(_input("wf_down"))
    assert result.failure == SafeActivityError(code="artifact_persistence_failed", retryable=True)
    assert not any((tmp_path / "reports" / "wf_down").rglob("*"))  # media cleaned up
```

(`_settings`, `_successful_runner`, `_capability`, `_input` stand for the helpers the file already uses for its success-path test; reuse those names or the file's equivalents. Existing tests that read `source-report.json` from `tmp_path` switch to `report_store.get(...)`.)

In the worker test module:

```python
def test_the_worker_refuses_to_start_without_the_editor_database() -> None:
    settings = Settings(THOTH_EDITOR_DATABASE_URL=None, ...)  # the module's minimal settings
    with pytest.raises(SettingsValidationError, match="editor_database_missing"):
        check_media_tools(settings)
```

- [ ] **Step 2: Run them to see them fail**

Run: `make test T=tests/activities/test_source_investigation.py`
Expected: FAIL — `build_source_investigation_activity() got an unexpected keyword argument 'reports'`.

- [ ] **Step 3: Implement** the behavior above. The persistence block becomes:

```python
    location = PurePosixPath("reports") / input_.workflow_id / "source-report.json"
    content = report.model_dump_json(indent=2, exclude_none=False).encode("utf-8")
    try:
        await asyncio.to_thread(reports.put, location.as_posix(), "source_report", content)
    except asyncio.CancelledError:
        _cleanup_after_persistence_failure(report, artifact_root)
        raise
    except ReportStoreUnavailable:
        _cleanup_after_persistence_failure(report, artifact_root)
        return SourceInvestigationActivityResult(
            failure=SafeActivityError(code="artifact_persistence_failed", retryable=True),
            events=_terminal_events(
                report.outcome.attempts, artifact_root, input_.workflow_id, platform,
                acquisition_result.account,
            ),
        )
```

`_run` gains a `reports: Reports` parameter; the builder resolves `selected_reports = reports or connect_reports(settings)` once, outside the activity function. `build_source_investigation_worker` resolves `reports = reports or connect_reports(settings)` and passes it to `build_source_investigation_activity`. Update every existing caller in tests to pass `reports=report_store`.

- [ ] **Step 4: Run the activity, workflow, and worker tests**

Run: `make test T="tests/activities/test_source_investigation.py tests/workflows/test_source_investigation.py tests/test_worker.py"` (use the worker test path you found)
Expected: PASS. The registered-root workflow test now asserts the row (`report_store.get("reports/wf_registered_root/source-report.json") is not None`) and that no file exists.

- [ ] **Step 5: Commit**

```bash
git add python/src/thoth_control_plane/activities/source_investigation.py python/src/thoth_control_plane/worker.py python/tests/activities/test_source_investigation.py python/tests/workflows/test_source_investigation.py <worker test file>
git commit -m "feat(reports): source investigation stores its report in PostgreSQL"
```

---

### Task 3: Attribution, assembly, and footage read and write through the store

**Files:**
- Modify: `python/src/thoth_control_plane/activities/content_assembly.py` (`_original`, `_attribution`, `_run`, `_write` removed, `build_content_assembly_activity`)
- Modify: `python/src/thoth_control_plane/activities/source_attribution.py` (`_run`, `_write` removed, `build_source_attribution_activity`)
- Modify: `python/src/thoth_control_plane/activities/footage.py` (`_run`, `build_footage_activity`)
- Modify: `python/src/thoth_control_plane/worker.py` (`build_source_investigation_worker` passes the same `reports` to all four builders)
- Test: `python/tests/activities/test_content_assembly.py`, `python/tests/activities/test_source_attribution.py`, `python/tests/activities/test_footage.py`, `python/tests/workflows/test_source_investigation.py`

**Interfaces:**
- Consumes: `Reports`, `read_report`, `ReportStoreUnavailable` (Task 1); the worker's shared `reports` (Task 2).
- Produces: `build_source_attribution_activity(settings, *, attributor=None, reports=None)`, `build_content_assembly_activity(settings, *, assembler=None, reports=None)`, `build_footage_activity(settings, *, builder=None, reports=None)`; shared readers `async def _original(reports, location) -> SourceReport | None` and `async def _attribution(reports, location) -> SourceAttribution | None` in `content_assembly.py` (footage keeps importing them).

Behavior:
- Every `(artifact_root / location).read_bytes()` of a report becomes `await read_report(reports, location, Model)`. `None` keeps today's path exactly: attribution `failed()` with its warning, footage `_done("unavailable", 0, started)`, assembly `_failed("source_report_missing", started)`, and the optional attribution/original reads returning `None`. The `ORIGINAL_LOCATION` / `ATTRIBUTION_LOCATION` regex checks stay in front of the reads.
- `ReportStoreUnavailable` is not caught in these three activities: it propagates as the activity error, so Temporal retries (`maximum_attempts` 2/2/3 in the workflow). After the last attempt the workflow behaves as it does today for an activity error (attribution continues without attribution, footage warns and continues, assembly fails).
- Writes: attribution stores `source_attribution` and, when present, `original_source_report` with `await asyncio.to_thread(reports.put, ...)`; assembly stores `content_set`. The `except OSError` around those writes is removed (a store error propagates, see above). Bytes and `ArtifactRef`s are produced exactly as today.
- `artifact_root` stays in these activities for media (`_video`, footage clips, frames).

- [ ] **Step 1: Write the failing tests**

`tests/activities/test_content_assembly.py` (reuse the file's fake assembler and report fixtures; reports are seeded with `report_store.put`):

```python
async def test_assembly_reads_the_stored_report_and_stores_the_content_set(
    tmp_path, report_store
) -> None:
    report_store.put("reports/wf_a/source-report.json", "source_report", _report_bytes())
    activity = build_content_assembly_activity(
        _settings(tmp_path), assembler=_FakeAssembler(), reports=report_store
    )
    result = await activity(ContentAssemblyActivityInput(workflow_id="wf_a"))

    stored = report_store.get("reports/wf_a/content-set.json")
    assert stored is not None
    assert result.content_set.checksum == f"sha256:{sha256(stored).hexdigest()}"
    assert not (tmp_path / "reports" / "wf_a" / "content-set.json").exists()


async def test_assembly_without_a_stored_report_is_source_report_missing(
    tmp_path, report_store
) -> None:
    activity = build_content_assembly_activity(
        _settings(tmp_path), assembler=_FakeAssembler(), reports=report_store
    )
    result = await activity(ContentAssemblyActivityInput(workflow_id="wf_none"))
    assert result.failure == "source_report_missing"


async def test_assembly_raises_when_the_database_is_down(tmp_path) -> None:
    activity = build_content_assembly_activity(
        _settings(tmp_path), assembler=_FakeAssembler(), reports=_DownReports()
    )
    with pytest.raises(ReportStoreUnavailable):
        await activity(ContentAssemblyActivityInput(workflow_id="wf_down"))
```

Add the same three shapes to `test_source_attribution.py` (stored attribution and original's report; absent report → `verdict == "unresolved"`; down → raises) and `test_footage.py` (absent → `footage_status == "unavailable"`; down → raises). `_DownReports` is the class from Task 2; move it to `tests/conftest.py` as a plain class `DownReports` so all three files import it.

- [ ] **Step 2: Run them to see them fail**

Run: `make test T="tests/activities/test_content_assembly.py tests/activities/test_source_attribution.py tests/activities/test_footage.py"`
Expected: FAIL — unexpected keyword argument `reports`.

- [ ] **Step 3: Implement** the behavior above. The shared readers become:

```python
async def _original(reports: Reports, location: str | None) -> SourceReport | None:
    if location is None or not ORIGINAL_LOCATION.fullmatch(location):
        return None
    return await read_report(reports, location, SourceReport)


async def _attribution(reports: Reports, location: str | None) -> SourceAttribution | None:
    if location is None or not ATTRIBUTION_LOCATION.fullmatch(location):
        return None
    return await read_report(reports, location, SourceAttribution)
```

Callers `await` them. Each builder resolves `selected_reports = reports or connect_reports(settings)`; `build_source_investigation_worker` passes its one `reports` to all four builders. Existing tests that wrote report files into `tmp_path` seed `report_store` instead.

- [ ] **Step 4: Run the activity and workflow tests**

Run: `make test T="tests/activities tests/workflows/test_source_investigation.py"`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add python/src/thoth_control_plane/activities/content_assembly.py python/src/thoth_control_plane/activities/source_attribution.py python/src/thoth_control_plane/activities/footage.py python/src/thoth_control_plane/worker.py python/tests/activities python/tests/workflows/test_source_investigation.py python/tests/conftest.py
git commit -m "feat(reports): attribution, assembly, and footage use stored reports"
```

---

### Task 4: Legacy Scout stores its report

**Files:**
- Modify: `python/src/thoth_control_plane/activities/legacy_scout.py` (`__init__`, `inspect`, `_argv`, `_artifact_path`, `build_legacy_scout_activity`)
- Modify: `python/src/thoth_control_plane/worker.py` (`run_worker` passes the shared `reports` to `build_legacy_scout_activity`)
- Test: `python/tests/activities/test_legacy_scout.py`

**Interfaces:**
- Consumes: `Reports`, `ReportStoreUnavailable` (Task 1).
- Produces: `LegacyScoutActivity(..., reports: Reports | None = None)`; `build_legacy_scout_activity(artifact_root: Path, reports: Reports)`.

Behavior:
- The Bun process writes to a scratch path `temp/legacy-scout/<workflow_id>/source-report.json` under the artifact root (passed as `--out`).
- After a zero exit: read the scratch bytes; a missing file keeps `legacy_scout_report_missing`. `await asyncio.to_thread(reports.put, "legacy-scout/<workflow_id>/source-report.json", "source_report", content)`; then the scratch directory is removed (`shutil.rmtree(..., ignore_errors=True)`) on every path out of `inspect` after the process ends (success or failure).
- `ReportStoreUnavailable` → the existing `legacy_scout_report_persistence_failed` failure result. `ReportInvalid` (the scout wrote non-JSON) → `legacy_scout_report_missing`.
- The `ArtifactRef.location` stays `legacy-scout/<workflow_id>/source-report.json`.
- `LegacyScoutActivity()` without `reports` (the module-level `inspect_legacy_scout` wrapper) uses `connect_reports(Settings())`.

- [ ] **Step 1: Write the failing tests** (reuse the file's fake process factory that writes the `--out` file):

```python
async def test_the_scout_report_is_stored_and_its_scratch_removed(tmp_path, report_store) -> None:
    adapter = LegacyScoutActivity(
        process_factory=_writes_report(b'{"schema_version": 1}'),
        artifact_root=tmp_path, reports=report_store,
    )
    result = await adapter.inspect(_input("wf_legacy"))

    assert report_store.get("legacy-scout/wf_legacy/source-report.json") == b'{"schema_version": 1}'
    assert result.report.location == "legacy-scout/wf_legacy/source-report.json"
    assert not (tmp_path / "temp" / "legacy-scout" / "wf_legacy").exists()
    assert not (tmp_path / "legacy-scout").exists()


async def test_a_database_outage_is_a_persistence_failure(tmp_path) -> None:
    adapter = LegacyScoutActivity(
        process_factory=_writes_report(b'{"schema_version": 1}'),
        artifact_root=tmp_path, reports=DownReports(),
    )
    result = await adapter.inspect(_input("wf_down"))
    assert result.failure.code == "legacy_scout_report_persistence_failed"
    assert not (tmp_path / "temp" / "legacy-scout" / "wf_down").exists()
```

(`_writes_report` / `_input` are the file's existing fake-process and input helpers; adapt the names.)

- [ ] **Step 2: Run to see them fail**

Run: `make test T=tests/activities/test_legacy_scout.py`
Expected: FAIL — unexpected keyword argument `reports`.

- [ ] **Step 3: Implement** the behavior above; existing tests asserting the file under `legacy-scout/` assert the stored row instead, and the `--out` argument assertions use the scratch path.

- [ ] **Step 4: Run**

Run: `make test T=tests/activities/test_legacy_scout.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add python/src/thoth_control_plane/activities/legacy_scout.py python/src/thoth_control_plane/worker.py python/tests/activities/test_legacy_scout.py
git commit -m "feat(reports): legacy Scout stores its report in PostgreSQL"
```

---

### Task 5: The API serves report artifacts from the store

**Files:**
- Modify: `python/src/thoth_control_plane/api/app.py` (`create_app` gains `report_store: Reports | None = None`; `app.state.report_store`)
- Modify: `python/src/thoth_control_plane/api/routes/workflows.py` (`download_workflow_artifact`)
- Test: `python/tests/api/test_workflows.py`

**Interfaces:**
- Consumes: `Reports`, `REPORT_KINDS`, `ReportStoreUnavailable`, `ReportStore.connect` (Task 1).

Behavior (Ruling R1 below):
- `create_app`: `report_store` or, when `THOTH_EDITOR_DATABASE_URL` is set, `ReportStore.connect(...)`; else `None`. This follows the API's existing rule that a missing database makes the database-backed feature unavailable while the rest still serves.
- Route: after the existing `service.get_artifact(...)` ownership check, an artifact whose `kind` is in `REPORT_KINDS`:
  - no store → `503` with detail `report_store_unavailable`;
  - `ReportStoreUnavailable` → `503` `report_store_unavailable`;
  - `None` → `ArtifactNotFound` (404 as today);
  - bytes → `Response(content, media_type=artifact.media_type, headers={"Content-Disposition": f'attachment; filename="{artifact.artifact_id}.json"'})`.
- Every other artifact keeps today's `FileResponse` path unchanged.

- [ ] **Step 1: Write the failing tests** (reuse the file's app/gateway fakes that already return an `ArtifactRef` for a workflow; the existing test near line 314 builds a source-report artifact):

```python
def test_a_report_artifact_is_served_from_the_store(report_store, ...) -> None:
    content = b'{"schema_version": 3}'
    report_store.put("reports/wf_api/source-report.json", "source_report", content)
    client = _client(report_store=report_store, artifact=_report_artifact("wf_api", content))

    response = client.get(f"/api/v1/workflows/wf_api/artifacts/{ARTIFACT_ID}", headers=AUTH)

    assert response.status_code == 200
    assert response.content == content
    assert response.headers["content-type"].startswith("application/json")


def test_a_missing_report_row_is_404(report_store, ...) -> None: ...
def test_a_report_without_a_store_is_503(...) -> None: ...          # report_store=None, no DB URL
def test_a_report_of_another_owner_is_still_refused(report_store, ...) -> None: ...
def test_a_media_artifact_is_still_served_from_disk(tmp_path, report_store, ...) -> None: ...
```

Write each body like the first: seed the store (or not), build the client with the file's existing fakes, assert the status (`404`, `503` with `report_store_unavailable`, the existing ownership status, `200` with the file bytes).

- [ ] **Step 2: Run to see them fail**

Run: `make test T=tests/api/test_workflows.py`
Expected: FAIL — `create_app() got an unexpected keyword argument 'report_store'`.

- [ ] **Step 3: Implement** the behavior above.

- [ ] **Step 4: Run**

Run: `make test T=tests/api`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add python/src/thoth_control_plane/api/app.py python/src/thoth_control_plane/api/routes/workflows.py python/tests/api/test_workflows.py
git commit -m "feat(reports): the API serves report artifacts from PostgreSQL"
```

---

### Task 6: `thoth-control reports import`

**Files:**
- Create: `python/src/thoth_control_plane/operations/report_import.py`
- Modify: `python/src/thoth_control_plane/cli.py` (a `reports` Typer group with `import`)
- Test: `python/tests/operations/test_report_import.py`

**Interfaces:**
- Consumes: `ReportStore.insert_missing`, `ReportInvalid` (Task 1); `ORIGINAL_LOCATION` from `activities/content_assembly.py`.
- Produces: `def import_reports(root: Path, store: ReportStore) -> ImportCounts` with `ImportCounts(imported: int, present: int, invalid: int)` (a frozen dataclass); CLI `thoth-control reports import --artifact-root PATH` printing `imported=<n> present=<n> invalid=<n>` and exiting 1 when `invalid > 0`.

Behavior:
- Candidates, and only these: `reports/*/source-report.json`, `reports/*/source-attribution.json`, `reports/*/content-set.json`, `legacy-scout/*/source-report.json`.
- Kind: `source-attribution.json` → `source_attribution`; `content-set.json` → `content_set`; `source-report.json` → `original_source_report` when its relative location matches `ORIGINAL_LOCATION`, else `source_report`.
- A candidate that is a symlink, or whose parent folder is a symlink, or that resolves outside the root, is skipped (not counted).
- `ReportInvalid` from the store (bad UTF-8, bad JSON, folder id that is not a safe segment) → `invalid += 1`; the import continues.
- `insert_missing` True → `imported += 1`; False → `present += 1`.
- Nothing is deleted. Output is counts only — no paths, no content.
- `ReportStoreUnavailable` stops the command with exit 1 and `report store unavailable`.

- [ ] **Step 1: Write the failing tests**

```python
from pathlib import Path

from thoth_control_plane.operations.report_import import ImportCounts, import_reports


def _write(root: Path, relative: str, content: bytes) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def test_imports_the_four_report_names_with_their_kinds(tmp_path, report_store) -> None:
    _write(tmp_path, "reports/wf_a/source-report.json", b'{"a": 1}')
    _write(tmp_path, "reports/wf_a/source-attribution.json", b'{"b": 1}')
    _write(tmp_path, "reports/wf_a/content-set.json", b'{"c": 1}')
    _write(tmp_path, "reports/wf_a-c1/source-report.json", b'{"d": 1}')
    _write(tmp_path, "legacy-scout/wf_b/source-report.json", b'{"e": 1}')

    assert import_reports(tmp_path, report_store) == ImportCounts(imported=5, present=0, invalid=0)
    assert report_store.get("reports/wf_a-c1/source-report.json") == b'{"d": 1}'


def test_a_rerun_imports_nothing_and_never_overwrites(tmp_path, report_store) -> None:
    _write(tmp_path, "reports/wf_a/source-report.json", b'{"a": 1}')
    import_reports(tmp_path, report_store)
    report_store.put("reports/wf_a/source-report.json", "source_report", b'{"newer": 1}')

    assert import_reports(tmp_path, report_store) == ImportCounts(imported=0, present=1, invalid=0)
    assert report_store.get("reports/wf_a/source-report.json") == b'{"newer": 1}'


def test_invalid_json_is_counted_and_the_rest_imported(tmp_path, report_store) -> None:
    _write(tmp_path, "reports/wf_a/source-report.json", b"not json")
    _write(tmp_path, "reports/wf_b/source-report.json", b'{"ok": 1}')
    assert import_reports(tmp_path, report_store) == ImportCounts(imported=1, present=0, invalid=1)


def test_other_files_and_links_are_ignored(tmp_path, report_store) -> None:
    _write(tmp_path, "reports/wf_a/media/clip.json", b"{}")
    _write(tmp_path, "reports/wf_a/footage/x.json", b"{}")
    _write(tmp_path, "renders/r1/metadata.json", b"{}")
    outside = tmp_path.parent / "outside.json"
    outside.write_bytes(b'{"secret": 1}')
    (tmp_path / "reports" / "wf_link").mkdir(parents=True)
    (tmp_path / "reports" / "wf_link" / "source-report.json").symlink_to(outside)

    assert import_reports(tmp_path, report_store) == ImportCounts(imported=0, present=0, invalid=0)
```

A CLI test with `typer.testing.CliRunner` asserts the printed line is exactly `imported=1 present=0 invalid=0` for one valid file (patch `ReportStore.connect` to return the `report_store` fixture and set `THOTH_EDITOR_DATABASE_URL`), and exit code 1 with `invalid=1`.

- [ ] **Step 2: Run to see them fail**

Run: `make test T=tests/operations/test_report_import.py`
Expected: FAIL — `ModuleNotFoundError: thoth_control_plane.operations.report_import`.

- [ ] **Step 3: Implement** the behavior above (`Path.glob` on the four patterns, `is_symlink()` on the file and its parent, `resolve().is_relative_to(root.resolve())`).

- [ ] **Step 4: Run**

Run: `make test T=tests/operations/test_report_import.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add python/src/thoth_control_plane/operations/report_import.py python/src/thoth_control_plane/cli.py python/tests/operations/test_report_import.py
git commit -m "feat(reports): import existing report files once"
```

---

### Task 7: The deploy imports, the runbook, the records, and the full verification

**Files:**
- Modify: `scripts/ops/deploy-stage1.sh`
- Modify: `python/tests/deployment/test_container_contract.py` (pin the deploy order)
- Modify: `docs/RUNNING.md` (a "Deploy with reports in PostgreSQL" section)
- Modify: `CHANGELOG.md`

Behavior of `scripts/ops/deploy-stage1.sh` after `config` (spec "Operations", operator 2026-10-16: the import is part of the deploy):

```bash
step migrate
"${compose[@]}" run --rm --no-deps api thoth-control editor migrate 2>&1 | tail -3
step stop-worker
"${compose[@]}" stop worker
step import-reports
import_line=$("${compose[@]}" run --rm --no-deps api thoth-control reports import \
    --artifact-root /var/lib/thoth/artifacts 2>&1 | tail -1)
echo "$import_line"
case "$import_line" in
    *" invalid=0") ;;
    *) echo "report import not clean; the old worker stays stopped — decide, then re-run" >&2
       exit 1 ;;
esac
step up
"${compose[@]}" up -d --wait 2>&1 | tail -12
```

(Confirm the artifact mount path inside the `api` service in `compose.stage1.local.yml` and use that value instead of `/var/lib/thoth/artifacts` if it differs.)

- [ ] **Step 1: Write the failing contract test**

```python
def test_the_deploy_imports_reports_with_the_old_worker_stopped() -> None:
    script = _repo_text("scripts/ops/deploy-stage1.sh")
    order = [
        script.index("editor migrate"),
        script.index("stop worker"),
        script.index("reports import"),
        script.index('" invalid=0"'),
        script.index("up -d --wait"),
    ]
    assert order == sorted(order)
```

Run: `make test T=tests/deployment/test_container_contract.py`
Expected: FAIL — `ValueError: substring not found`.

- [ ] **Step 2: Change the deploy script** as above. Run the contract test again. Expected: PASS.

- [ ] **Step 3: Runbook** — in `docs/RUNNING.md`, a section stating: reports live in PostgreSQL; `make deploy` runs migrate → stop worker → import → `invalid=0` check → up; back up PostgreSQL and the artifact volume together; every workflow depends on the editor PostgreSQL; never roll the image back while workflows are in flight.

- [ ] **Step 4: Full verification**

Run, in order, and read every result:
- `make lint` — Expected: clean.
- `make test` — Expected: 0 failed.
- `make test-postgres` — Expected: 0 failed, 0 skipped.
- `make dashboard-test` — Expected: 0 fail (the API contract the dashboard reads did not change).
- `grep -rn "source-report.json\|content-set.json\|source-attribution.json" python/src | grep -v "location\|LOCATION\|_FILE ="` — Expected: no report file read or write left (only location strings).

- [ ] **Step 5: Records** — `CHANGELOG.md` entry "2026-10-16 - Workflow reports in PostgreSQL" with what changed, the verification counts, and **Next steps**: PR + CI (the quality job now runs the Postgres tests), merge, digest, operator pins the digest, `make deploy` (which imports), then one workflow end to end and a check that its report rows exist; follow-up: media to S3 (its own spec).

- [ ] **Step 6: Commit**

```bash
git add scripts/ops/deploy-stage1.sh python/tests/deployment/test_container_contract.py docs/RUNNING.md CHANGELOG.md
git commit -m "docs(reports): deploy imports reports with the old worker stopped"
```

---

## Rulings made while planning

- **R1 — API without the database answers 503, it does not refuse to start.** The spec says the API fails at startup without `THOTH_EDITOR_DATABASE_URL`. The API's established contract (`api/app.py`, "a missing database or renderer only makes render unavailable: every other part of the control plane must still start and serve") and its 17 test modules that build the app without a database say otherwise. The worker — which writes and reads every report — does fail at startup (Task 2). Cost if wrong: one startup check in `create_app` and test fixtures that set the URL.
- **R2 — A store error in attribution, assembly, and footage propagates as the activity error.** The workflow retries them 2, 2, and 3 times; after the last attempt it treats the error as it treats any activity error today (attribution continues without attribution, footage continues, assembly fails the run). Source investigation keeps its typed `artifact_persistence_failed`; legacy Scout uses its existing `legacy_scout_report_persistence_failed`.
- **R3 — The import exits 1 when `invalid > 0`** so the deploy can stop on it (spec: "a check that step 3 printed `invalid=0`").
