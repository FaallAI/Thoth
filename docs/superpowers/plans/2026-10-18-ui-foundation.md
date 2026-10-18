# UI Foundation and Voice Adapter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the dashboard a durable spine and add a voice adapter. The spine is projects in
the control plane, stored and listed workflows, Studio drafts per project, media downloads that
work, and URL routing. The voice adapter has two providers, ElevenLabs and OpenAI-compatible.

**Architecture:**
- Two new editor-database tables (`projects`, `workflow_runs`) behind SQLAlchemy stores, as with
  `report_store.py`.
- A `WorkflowRunService` that records each start and settles runs when they are read, through a
  new gateway `settle` call that uses Temporal `describe` and `result`.
- The dashboard gains React Router v7 (declarative) with routes for workflows and Studio
  documents.
- The voice port lives in `thoth_control_plane/voice/`, with an operator-only CLI.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2, Alembic (SQL files), temporalio, httpx,
openai, PyAV; React 19, react-router 7, Bun test with happy-dom.

**Spec:** `docs/superpowers/specs/2026-10-18-ui-foundation-design.md` (approved 2026-10-18; edge-tts removed the same day).

## Global Constraints

- Repository text is English; operator chat is Indonesian.
- Commits: exactly one `git commit -m "<subject>"`, at most ~72 characters, with no body,
  trailer or AI attribution.
- Never stage `.superpowers/`, `graphify-out/`, `.serena/`, the `.codegraph` database, or the
  untracked `design/` files. `docs/superpowers/` is gitignored: use `git add -f`.
- No live provider or platform calls in tests. The conftest guard blocks non-loopback traffic.
- Store I/O from async code goes through `asyncio.to_thread`.
- A missing database or provider degrades with a typed error (503 or a clear CLI message),
  never silently.
- **Python tests:** run from WSL at the worktree root,
  `wsl -e bash -lc 'cd /mnt/d/thoth-tmp/wt-ui-foundation && make test T=<path relative to python/>'`.
- **Lint:** `make lint`.
- **Postgres tests:** `make test-postgres`.
- **Dashboard tests:** `cd dashboard && bun test <path>`.
- **Dashboard build:** `cd dashboard && bun run build`.
- **Contract regeneration:** `uv run --project python python python/scripts/export_openapi.py`,
  then `cd dashboard && bun run generate:control-plane-types`.
- **Voice:** two providers only, `elevenlabs` and `openai_compatible`. **edge-tts is excluded**
  (operator, 2026-10-18).

## Rulings Taken While Planning

Spec deviations, each with what it costs if wrong:

- **P1:** `workflow_runs.workflow_id` is checked by length (1–128), not by `^wf_[0-9a-f]{24}$`.
  The test gateway mints `wf_001`; the backfill still filters by the strict pattern. Cost: a
  malformed ID could be stored by a future caller.
- **P2:** `WorkflowSummary` gains `history_expired: bool = False`, so `GET /workflows/{id}` can
  tell the detail page that the history expired. The field is additive with a default, and old
  Temporal histories deserialize unchanged. Cost: one more contract field.
- **P3:** a synthesized summary must use a `WorkflowStatus`, and that enum has no `unknown`. It
  therefore reports `succeeded`; every backfilled workflow wrote its source report. The run
  list keeps `unknown` and `history_expired`. Cost: a run that failed after its source report
  shows `succeeded` in its expired detail.
- **P4:** `gateway.settle(workflow_id)` takes no actor. Authorization is the stored row's actor,
  checked before settling, so a closed workflow is never replayed just to read its owner. Cost:
  none while the bearer maps to one actor.
- **P5:** `BrowserRouter` lives inside `App` rather than `main.tsx`, so tests that render
  `<App />` keep working. Deep links in tests use `history.replaceState`. Cost: none.
- **P6:** `streamWorkflow` stops reconnecting after a terminal or history-expired snapshot. Today
  it polls every second forever. Cost: a terminal workflow that is later retried needs a reload.

## Review Focus

- A retried start, after the row write failed with 503, must create the row and no second
  workflow. Test in Task 5.
- A project page that lists runs while Temporal is down must still answer 200 with the stored
  rows. Test in Task 5.
- An artifact download with a `Range` header returns 206 from the store, and a missing object
  returns 404, not 500. Test in Task 7.
- The active project, stored in `localStorage`, may name a deleted project. The switcher then
  falls back to the first project instead of showing an empty selection. Test in Task 13.
- A deep link reloaded on `/studio/:project/:doc` renders Studio without any Content Set state.
  Test in Task 13.

---

### Task 1: Migration 0012 and the ORM models

**Files:**
- Create: `python/migrations/editor/0012_projects_and_workflow_runs.sql`
- Create: `python/migrations/editor/alembic/versions/0012_projects_and_workflow_runs.py`
- Create: `python/src/thoth_control_plane/infrastructure/run_models.py`
- Modify: `python/tests/operations/test_editor_migrations.py` (the `MIGRATION_FILES` pin)
- Modify: `python/tests/operations/test_editor_migrations_postgres.py` (counts 11→12, 5→6)
- Test: `python/tests/infrastructure/test_run_models.py`

**Interfaces:**
- Produces: `ProjectRow` and `WorkflowRunRow`, mapped on the shared `Base` from
  `source_account_models.py`.

- [ ] **Step 1: Write the failing tests**

`python/tests/infrastructure/test_run_models.py`:
```python
"""The projects and workflow_runs ORM tables round-trip on SQLite."""

from datetime import UTC, datetime

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from thoth_control_plane.infrastructure.run_models import ProjectRow, WorkflowRunRow
from thoth_control_plane.infrastructure.source_account_models import Base

NOW = datetime(2026, 10, 18, 8, tzinfo=UTC)


def test_a_run_belongs_to_a_project_and_keeps_its_summary() -> None:
    engine = create_engine("sqlite://", poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(ProjectRow(project_id="p1", name="News", created_at=NOW, updated_at=NOW))
        session.add(
            WorkflowRunRow(
                workflow_id="wf_001", project_id="p1", actor_type="user", actor_id="owner",
                display_url="https://example.test/post", platform="example", status="queued",
                history_expired=False, summary={"workflow_id": "wf_001"},
                created_at=NOW, updated_at=NOW,
            )
        )
        session.commit()
        row = session.scalar(select(WorkflowRunRow))
    assert row is not None and row.project_id == "p1" and row.summary == {"workflow_id": "wf_001"}
    assert row.created_at == NOW
```

In `test_editor_migrations.py`, append `"0012_projects_and_workflow_runs.sql",` to the
`MIGRATION_FILES` list in `test_editor_migrations_stay_explicit_forward_only_sql_files`. In
`test_editor_migrations_postgres.py`:
- change `== 11` to `== 12` in `test_fresh_database_applies_every_revision_and_a_rerun_applies_none`,
  and add `assert {"projects", "workflow_runs"} <= _tables()`;
- change `== 5` to `== 6` in `test_database_migrated_before_alembic_is_adopted_and_only_the_rest_applied`.

- [ ] **Step 2: Run them to verify they fail**

Run: `make test T=tests/infrastructure/test_run_models.py tests/operations/test_editor_migrations.py`
Expected: FAIL. The import fails with `No module named ...run_models`, and the migration list
lacks 0012.

- [ ] **Step 3: Write the migration and the models**

`python/migrations/editor/0012_projects_and_workflow_runs.sql`:
```sql
-- Projects and workflow runs (spec 2026-10-18, UI foundation). Projects move into the control
-- plane; a run row is written when a workflow starts and settled when it is read.

CREATE TABLE projects (
    project_id TEXT PRIMARY KEY CHECK (char_length(project_id) BETWEEN 1 AND 128),
    name TEXT NOT NULL CHECK (char_length(btrim(name)) BETWEEN 1 AND 120),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE workflow_runs (
    workflow_id TEXT PRIMARY KEY CHECK (char_length(workflow_id) BETWEEN 1 AND 128),
    project_id TEXT REFERENCES projects (project_id),
    actor_type TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    display_url TEXT NOT NULL CHECK (char_length(display_url) BETWEEN 1 AND 2048),
    platform TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN (
        'queued', 'running', 'awaiting_approval', 'succeeded', 'failed', 'cancelled', 'unknown')),
    history_expired BOOLEAN NOT NULL DEFAULT false,
    summary JSONB,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX workflow_runs_project ON workflow_runs (project_id, created_at DESC, workflow_id DESC);
CREATE INDEX workflow_runs_unsettled ON workflow_runs (status)
    WHERE status IN ('queued', 'running', 'awaiting_approval', 'unknown');
```

`python/migrations/editor/alembic/versions/0012_projects_and_workflow_runs.py`:
```python
"""Apply the shipped 0012_projects_and_workflow_runs.sql verbatim."""

from thoth_control_plane.operations.editor_migrations import execute_sql_file

revision = "0012"
down_revision = "0011"


def upgrade() -> None:
    execute_sql_file(__file__)
```

`python/src/thoth_control_plane/infrastructure/run_models.py`:
```python
"""SQLAlchemy ORM mapping of the projects and workflow_runs tables (editor migration 0012)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from thoth_control_plane.infrastructure.source_account_models import Base, UtcDateTime


class ProjectRow(Base):
    __tablename__ = "projects"

    project_id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime)


class WorkflowRunRow(Base):
    __tablename__ = "workflow_runs"

    workflow_id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("projects.project_id"), nullable=True
    )
    actor_type: Mapped[str] = mapped_column(String)
    actor_id: Mapped[str] = mapped_column(String)
    display_url: Mapped[str] = mapped_column(String)
    platform: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String)
    history_expired: Mapped[bool] = mapped_column(Boolean, default=False)
    summary: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `make test T=tests/infrastructure/test_run_models.py tests/operations/test_editor_migrations.py`
Expected: PASS. Then run `make test-postgres` and expect PASS, including the 12/6 counts.

- [ ] **Step 5: Commit**

```bash
git add python/migrations/editor/0012_projects_and_workflow_runs.sql python/migrations/editor/alembic/versions/0012_projects_and_workflow_runs.py python/src/thoth_control_plane/infrastructure/run_models.py python/tests/infrastructure/test_run_models.py python/tests/operations/test_editor_migrations.py python/tests/operations/test_editor_migrations_postgres.py
git commit -m "feat(db): add the projects and workflow_runs tables"
```

### Task 2: Projects: domain, store, routes, and the import CLI

**Files:**
- Create: `python/src/thoth_control_plane/domain/projects.py`
- Create: `python/src/thoth_control_plane/infrastructure/project_store.py`
- Create: `python/src/thoth_control_plane/api/routes/projects.py`
- Modify: `python/src/thoth_control_plane/api/app.py` (a `project_store` param, `app.state.project_store`, router include, 503 mapping)
- Modify: `python/src/thoth_control_plane/cli.py` (`projects import`)
- Test: `python/tests/infrastructure/test_project_store.py`, `python/tests/api/test_projects.py`, `python/tests/test_cli.py`

**Interfaces:**
- Produces:
  - `Project(project_id, name, created_at, updated_at)`, `CreateProject(name)`, `ProjectList(items)`;
  - `ProjectStore(engine)` with `.connect(url)`, `.list() -> list[Project]`,
    `.get(project_id) -> Project | None`, `.create(name) -> Project` and
    `.insert_missing(project) -> bool`;
  - `ProjectStoreUnavailable`;
  - `create_app(..., project_store=...)`.

- [ ] **Step 1: Write the failing store tests**

`python/tests/infrastructure/test_project_store.py`:
```python
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from thoth_control_plane.domain.projects import Project
from thoth_control_plane.infrastructure import run_models  # noqa: F401  (registers the tables)
from thoth_control_plane.infrastructure.project_store import ProjectStore
from thoth_control_plane.infrastructure.source_account_models import Base


@pytest.fixture
def store() -> ProjectStore:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return ProjectStore(engine)


def test_create_mints_a_uuid_and_trims_the_name(store: ProjectStore) -> None:
    project = store.create("  News  ")
    assert project.name == "News"
    assert len(project.project_id) == 36
    assert store.get(project.project_id) == project


def test_list_is_newest_updated_first(store: ProjectStore) -> None:
    first = store.create("A")
    second = store.create("B")
    assert [p.project_id for p in store.list()] == [second.project_id, first.project_id]


def test_insert_missing_keeps_the_id_and_never_overwrites(store: ProjectStore) -> None:
    when = datetime(2026, 9, 1, tzinfo=UTC)
    legacy = Project(project_id="db766411-3cb0-47a4-9dc9-b67d22f6f34e", name="test", created_at=when, updated_at=when)
    assert store.insert_missing(legacy) is True
    assert store.insert_missing(legacy.model_copy(update={"name": "other"})) is False
    assert store.get(legacy.project_id) == legacy
```

- [ ] **Step 2: Run them to verify they fail**

Run: `make test T=tests/infrastructure/test_project_store.py`
Expected: FAIL with `No module named ...domain.projects`.

- [ ] **Step 3: Implement the domain and the store**

`python/src/thoth_control_plane/domain/projects.py`:
```python
"""Projects owned by the control plane (spec 2026-10-18, section 3.2)."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import Field, field_validator

from thoth_control_plane.domain.models import ProjectId, StrictModel

ProjectName = Annotated[str, Field(min_length=1, max_length=120)]


class Project(StrictModel):
    project_id: ProjectId
    name: ProjectName
    created_at: datetime
    updated_at: datetime


class CreateProject(StrictModel):
    name: Annotated[str, Field(min_length=1, max_length=200)]

    @field_validator("name")
    @classmethod
    def _trimmed(cls, name: str) -> str:
        name = name.strip()
        if not 1 <= len(name) <= 120:
            raise ValueError("name must be 1-120 characters after trimming")
        return name


class ProjectList(StrictModel):
    items: list[Project]
```

`python/src/thoth_control_plane/infrastructure/project_store.py`:
```python
"""Projects in PostgreSQL (editor migration 0012). Synchronous; callers use asyncio.to_thread."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import create_engine, select
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from thoth_control_plane.domain.projects import Project
from thoth_control_plane.infrastructure.run_models import ProjectRow

logger = logging.getLogger(__name__)


class ProjectStoreUnavailable(RuntimeError):
    """The database could not be reached or refused the statement."""


def _project(row: ProjectRow) -> Project:
    return Project(
        project_id=row.project_id, name=row.name, created_at=row.created_at, updated_at=row.updated_at
    )


class ProjectStore:
    def __init__(self, engine: Engine, clock: Callable[[], datetime] = lambda: datetime.now(UTC)) -> None:
        self._sessions = sessionmaker(engine, expire_on_commit=False)
        self._clock = clock

    @classmethod
    def connect(cls, database_url: str) -> ProjectStore:
        url = make_url(database_url).set(drivername="postgresql+psycopg")
        return cls(
            create_engine(
                url, pool_pre_ping=True, pool_size=2, max_overflow=2, hide_parameters=True,
                connect_args={"connect_timeout": 10},
            )
        )

    def list(self) -> list[Project]:
        try:
            with self._sessions() as session:
                rows = session.scalars(
                    select(ProjectRow).order_by(ProjectRow.updated_at.desc(), ProjectRow.project_id.desc())
                ).all()
        except SQLAlchemyError as error:
            logger.warning("project store failed: %s", type(error).__name__)
            raise ProjectStoreUnavailable("project_store_unavailable") from None
        return [_project(row) for row in rows]

    def get(self, project_id: str) -> Project | None:
        try:
            with self._sessions() as session:
                row = session.get(ProjectRow, project_id)
        except SQLAlchemyError as error:
            logger.warning("project store failed: %s", type(error).__name__)
            raise ProjectStoreUnavailable("project_store_unavailable") from None
        return None if row is None else _project(row)

    def create(self, name: str) -> Project:
        now = self._clock()
        row = ProjectRow(project_id=str(uuid4()), name=name.strip(), created_at=now, updated_at=now)
        try:
            with self._sessions.begin() as session:
                session.add(row)
        except SQLAlchemyError as error:
            logger.warning("project store failed: %s", type(error).__name__)
            raise ProjectStoreUnavailable("project_store_unavailable") from None
        return _project(row)

    def insert_missing(self, project: Project) -> bool:
        try:
            with self._sessions.begin() as session:
                if session.get(ProjectRow, project.project_id) is not None:
                    return False
                session.add(ProjectRow(**project.model_dump()))
                return True
        except SQLAlchemyError as error:
            logger.warning("project store failed: %s", type(error).__name__)
            raise ProjectStoreUnavailable("project_store_unavailable") from None
```

- [ ] **Step 4: Run the store tests to verify they pass**

Run: `make test T=tests/infrastructure/test_project_store.py`
Expected: PASS (3 tests). If `test_list_is_newest_updated_first` ties on the timestamp, pass a
monotonic `clock` in the fixture: `ProjectStore(engine, clock=iter([...]).__next__)`.

- [ ] **Step 5: Write the failing API and CLI tests**

`python/tests/api/test_projects.py`:
```python
import httpx
import pytest
import pytest_asyncio
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from thoth_control_plane.api import create_app
from thoth_control_plane.config import Settings
from thoth_control_plane.infrastructure import run_models  # noqa: F401
from thoth_control_plane.infrastructure.project_store import ProjectStore, ProjectStoreUnavailable
from thoth_control_plane.infrastructure.source_account_models import Base

AUTH = {"Authorization": "Bearer test-key"}


@pytest_asyncio.fixture
async def api(gateway):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    app = create_app(Settings(THOTH_CONTROL_PLANE_API_KEY="test-key"), gateway, project_store=ProjectStore(engine))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield client


@pytest.mark.asyncio
async def test_create_then_list_and_get(api) -> None:
    created = await api.post("/api/v1/projects", json={"name": " News "}, headers=AUTH)
    assert created.status_code == 201 and created.json()["name"] == "News"
    listed = await api.get("/api/v1/projects", headers=AUTH)
    assert [p["name"] for p in listed.json()["items"]] == ["News"]
    one = await api.get(f"/api/v1/projects/{created.json()['project_id']}", headers=AUTH)
    assert one.status_code == 200


@pytest.mark.asyncio
async def test_unknown_project_is_404_and_blank_name_is_422(api) -> None:
    assert (await api.get("/api/v1/projects/nope", headers=AUTH)).json() == {"detail": "project_not_found"}
    assert (await api.post("/api/v1/projects", json={"name": "   "}, headers=AUTH)).status_code == 422


@pytest.mark.asyncio
async def test_no_database_answers_503(gateway) -> None:
    app = create_app(Settings(THOTH_CONTROL_PLANE_API_KEY="test-key"), gateway)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/projects", headers=AUTH)
    assert response.status_code == 503 and response.json() == {"detail": "project_store_unavailable"}


@pytest.mark.asyncio
async def test_a_store_failure_answers_503(gateway) -> None:
    class Down:
        def list(self):
            raise ProjectStoreUnavailable("project_store_unavailable")

    app = create_app(Settings(THOTH_CONTROL_PLANE_API_KEY="test-key"), gateway, project_store=Down())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get("/api/v1/projects", headers=AUTH)).status_code == 503
```

Append to `python/tests/test_cli.py`:
```python
def test_projects_import_reads_the_rust_json_from_stdin(monkeypatch, tmp_path) -> None:
    from sqlalchemy import create_engine
    from sqlalchemy.pool import StaticPool
    from typer.testing import CliRunner

    from thoth_control_plane import cli
    from thoth_control_plane.infrastructure import run_models  # noqa: F401
    from thoth_control_plane.infrastructure.project_store import ProjectStore
    from thoth_control_plane.infrastructure.source_account_models import Base

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    store = ProjectStore(engine)
    monkeypatch.setenv("THOTH_CONTROL_PLANE_API_KEY", "k")
    monkeypatch.setenv("THOTH_EDITOR_DATABASE_URL", "postgresql://unused/db")
    monkeypatch.setattr(cli.ProjectStore, "connect", classmethod(lambda cls, url: store))
    rows = '[{"id": "db766411-3cb0-47a4-9dc9-b67d22f6f34e", "name": "test", "workspace_path": "x", "created_at": "2026-09-01T00:00:00Z", "updated_at": "2026-09-01T00:00:00Z"}, {"id": "", "name": "bad"}]'
    result = CliRunner().invoke(cli.app, ["projects", "import", "-"], input=rows)
    assert result.output.strip().splitlines()[-1] == "imported=1 present=0 invalid=1"
    assert result.exit_code == 1
    again = CliRunner().invoke(cli.app, ["projects", "import", "-"], input=rows[:rows.index(", {")] + "]")
    assert again.output.strip().splitlines()[-1] == "imported=0 present=1 invalid=0"
```

- [ ] **Step 6: Run them to verify they fail**

Run: `make test T=tests/api/test_projects.py tests/test_cli.py`
Expected: FAIL. `create_app()` rejects the unexpected `project_store` keyword, and the `projects`
command does not exist.

- [ ] **Step 7: Implement the routes, the wiring, and the CLI**

`python/src/thoth_control_plane/api/routes/projects.py`:
```python
"""Projects owned by the control plane."""

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status

from thoth_control_plane.api.dependencies import current_actor
from thoth_control_plane.application import Actor
from thoth_control_plane.domain.projects import CreateProject, Project, ProjectList
from thoth_control_plane.infrastructure.project_store import ProjectStoreUnavailable

router = APIRouter()


def project_store(request: Request):
    store = request.app.state.project_store
    if store is None:
        raise ProjectStoreUnavailable("project_store_unavailable")
    return store


@router.get("/projects", response_model=ProjectList)
async def list_projects(
    actor: Annotated[Actor, Depends(current_actor)], store=Depends(project_store)
) -> ProjectList:
    return ProjectList(items=await asyncio.to_thread(store.list))


@router.post("/projects", response_model=Project, status_code=status.HTTP_201_CREATED)
async def create_project(
    body: CreateProject, actor: Annotated[Actor, Depends(current_actor)], store=Depends(project_store)
) -> Project:
    return await asyncio.to_thread(store.create, body.name)


@router.get("/projects/{project_id}", response_model=Project)
async def get_project(
    project_id: str, actor: Annotated[Actor, Depends(current_actor)], store=Depends(project_store)
) -> Project:
    project = await asyncio.to_thread(store.get, project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="project_not_found")
    return project
```

In `api/app.py`:
- add the `project_store: ProjectStore | None = None` parameter after `report_store`;
- after the `report_store` block, add:
  ```python
  if project_store is None and settings.THOTH_EDITOR_DATABASE_URL is not None:
      project_store = ProjectStore.connect(settings.THOTH_EDITOR_DATABASE_URL.get_secret_value())
  app.state.project_store = project_store
  ```
- add `ProjectStoreUnavailable` to the handler map so it answers
  `JSONResponse(status_code=503, content={"detail": "project_store_unavailable"})`, in its own
  `@app.exception_handler(ProjectStoreUnavailable)` next to the `UnsupportedPlatform` handler;
- include `projects.router` with the same `prefix="/api/v1"` and dependencies as the workflows
  router (follow the existing `include_router` lines in `app.py`).

In `cli.py`, add after `reports_app`:
```python
projects_app = typer.Typer(no_args_is_help=True)
app.add_typer(projects_app, name="projects")


@projects_app.command("import")
def projects_import(source: Annotated[str, typer.Argument(help="JSON file from Rust /api/projects, or - for stdin")]) -> None:
    """Insert the Rust server's projects with their IDs; never overwrite. Counts only."""
    import sys

    from pydantic import ValidationError

    from thoth_control_plane.domain.projects import Project

    database_url = Settings().THOTH_EDITOR_DATABASE_URL
    if database_url is None:
        raise typer.BadParameter("THOTH_EDITOR_DATABASE_URL must be configured")
    text = sys.stdin.read() if source == "-" else Path(source).read_text(encoding="utf-8")
    store = ProjectStore.connect(database_url.get_secret_value())
    imported = present = invalid = 0
    for item in json.loads(text):
        try:
            project = Project(
                project_id=item["id"], name=str(item["name"]).strip(),
                created_at=item["created_at"], updated_at=item["updated_at"],
            )
        except (KeyError, TypeError, ValidationError):
            invalid += 1
            continue
        try:
            inserted = store.insert_missing(project)
        except ProjectStoreUnavailable:
            typer.echo("project store unavailable")
            raise typer.Exit(1) from None
        imported, present = imported + inserted, present + (not inserted)
    typer.echo(f"imported={imported} present={present} invalid={invalid}")
    if invalid:
        raise typer.Exit(1)
```
Add the module imports `json` and
`from thoth_control_plane.infrastructure.project_store import ProjectStore, ProjectStoreUnavailable`
at the top of `cli.py`, next to the existing `ReportStore` import.

- [ ] **Step 8: Run the tests to verify they pass**

Run: `make test T=tests/api/test_projects.py tests/test_cli.py tests/infrastructure/test_project_store.py`
Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add python/src/thoth_control_plane/domain/projects.py python/src/thoth_control_plane/infrastructure/project_store.py python/src/thoth_control_plane/api/routes/projects.py python/src/thoth_control_plane/api/app.py python/src/thoth_control_plane/cli.py python/tests/infrastructure/test_project_store.py python/tests/api/test_projects.py python/tests/test_cli.py
git commit -m "feat(projects): projects in the control plane with an import CLI"
```

### Task 3: The workflow run store and its models

**Files:**
- Create: `python/src/thoth_control_plane/domain/workflow_runs.py`
- Create: `python/src/thoth_control_plane/infrastructure/workflow_run_store.py`
- Modify: `python/src/thoth_control_plane/domain/models.py` (`WorkflowSummary.history_expired`, ruling P2)
- Test: `python/tests/infrastructure/test_workflow_run_store.py`

**Interfaces:**
- Consumes: `WorkflowRunRow`, `ProjectRow` (Task 1); `WorkflowReportRow` (existing).
- Produces:
  - `WorkflowRunStatus`;
  - `UNSETTLED: frozenset[str]`;
  - `WorkflowRun`, `WorkflowRunPage` and `MoveWorkflow` (`project_id`);
  - `StoredRun` (frozen dataclass, with `.to_run() -> WorkflowRun`);
  - `WorkflowRunsUnavailable`;
  - `WorkflowRunStore(engine)` with:
    - `.connect(url)`;
    - `record_start(summary, *, project_id, actor)`;
    - `page(*, project_id, unassigned, actor, cursor, limit) -> tuple[list[StoredRun], str | None]`;
    - `get(workflow_id) -> StoredRun | None`;
    - `settle(workflow_id, *, status, summary, history_expired)`;
    - `assign(workflow_id, project_id) -> StoredRun | None`;
    - `insert_missing(run: StoredRun) -> bool`;
    - `report_artifacts(workflow_id) -> list[ArtifactRef]`;
    - `source_report_rows() -> list[tuple[str, str, datetime]]`, as
      (workflow_id, content, earliest created_at of that workflow's reports).

- [ ] **Step 1: Write the failing tests**

`python/tests/infrastructure/test_workflow_run_store.py`:
```python
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from thoth_control_plane.domain import Actor, WorkflowSummary
from thoth_control_plane.infrastructure import run_models  # noqa: F401
from thoth_control_plane.infrastructure.project_store import ProjectStore
from thoth_control_plane.infrastructure.report_store import ReportStore
from thoth_control_plane.infrastructure.source_account_models import Base
from thoth_control_plane.infrastructure.workflow_run_store import WorkflowRunStore

OWNER = Actor(actor_id="owner", actor_type="user")
T0 = datetime(2026, 10, 18, 8, tzinfo=UTC)


def summary(workflow_id: str, status: str = "queued") -> WorkflowSummary:
    return WorkflowSummary(
        workflow_id=workflow_id, status=status, created_at=T0, updated_at=T0,
        source={"display_url": "https://example.test/post", "platform": "example"}, stages=[],
    )


@pytest.fixture
def stores():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    ticks = iter(T0 + timedelta(seconds=n) for n in range(1000))
    return ProjectStore(engine), WorkflowRunStore(engine, clock=lambda: next(ticks)), ReportStore(engine)


def test_record_start_is_an_upsert_that_never_moves_the_project(stores) -> None:
    projects, runs, _ = stores
    project = projects.create("News")
    runs.record_start(summary("wf_a"), project_id=project.project_id, actor=OWNER)
    runs.record_start(summary("wf_a", "running"), project_id=None, actor=OWNER)
    stored = runs.get("wf_a")
    assert stored is not None and stored.project_id == project.project_id and stored.status == "running"


def test_pages_are_per_project_newest_first_with_a_cursor(stores) -> None:
    projects, runs, _ = stores
    project = projects.create("News")
    for name in ("wf_a", "wf_b", "wf_c"):
        runs.record_start(summary(name), project_id=project.project_id, actor=OWNER)
    runs.record_start(summary("wf_x"), project_id=None, actor=OWNER)
    first, cursor = runs.page(project_id=project.project_id, unassigned=False, actor=OWNER, cursor=None, limit=2)
    assert [r.workflow_id for r in first] == ["wf_c", "wf_b"] and cursor
    rest, end = runs.page(project_id=project.project_id, unassigned=False, actor=OWNER, cursor=cursor, limit=2)
    assert [r.workflow_id for r in rest] == ["wf_a"] and end is None
    loose, _ = runs.page(project_id=None, unassigned=True, actor=OWNER, cursor=None, limit=50)
    assert [r.workflow_id for r in loose] == ["wf_x"]


def test_another_actor_sees_nothing(stores) -> None:
    _, runs, _ = stores
    runs.record_start(summary("wf_a"), project_id=None, actor=OWNER)
    other = Actor(actor_id="someone", actor_type="user")
    assert runs.page(project_id=None, unassigned=True, actor=other, cursor=None, limit=50) == ([], None)


def test_settle_and_assign(stores) -> None:
    projects, runs, _ = stores
    runs.record_start(summary("wf_a"), project_id=None, actor=OWNER)
    runs.settle("wf_a", status="succeeded", summary=summary("wf_a", "succeeded"), history_expired=False)
    project = projects.create("News")
    moved = runs.assign("wf_a", project.project_id)
    assert moved is not None and moved.project_id == project.project_id and moved.status == "succeeded"
    assert moved.to_run().artifact_count == 0
    assert runs.assign("wf_missing", project.project_id) is None


def test_report_artifacts_and_source_rows_come_from_workflow_reports(stores) -> None:
    _, runs, reports = stores
    reports.put("reports/wf_a/source-report.json", "source_report", b'{"source": {"canonical_url": "https://x.test/v?a=1", "platform": "tiktok"}}')
    reports.put("reports/wf_a/content-set.json", "content_set", b"{}")
    artifacts = runs.report_artifacts("wf_a")
    assert {a.artifact_id for a in artifacts} == {"source_report", "content_set"}
    assert all(a.media_type == "application/json" and a.checksum.startswith("sha256:") for a in artifacts)
    [(workflow_id, content, _)] = runs.source_report_rows()
    assert workflow_id == "wf_a" and "canonical_url" in content
```

- [ ] **Step 2: Run them to verify they fail**

Run: `make test T=tests/infrastructure/test_workflow_run_store.py`
Expected: FAIL with `No module named ...workflow_run_store`.

- [ ] **Step 3: Implement**

In `domain/models.py`, inside `class WorkflowSummary`, add after
`failure: WorkflowFailure | None = None`:
```python
    history_expired: bool = False
```

`python/src/thoth_control_plane/domain/workflow_runs.py`:
```python
"""Stored workflow runs, listed per project (spec 2026-10-18, section 3.3)."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field

from thoth_control_plane.domain.models import OpaqueId, ProjectId, StrictModel, WorkflowSource

WorkflowRunStatus = Literal[
    "queued", "running", "awaiting_approval", "succeeded", "failed", "cancelled", "unknown"
]
UNSETTLED = frozenset({"queued", "running", "awaiting_approval", "unknown"})


class WorkflowRun(StrictModel):
    workflow_id: OpaqueId
    project_id: ProjectId | None
    source: WorkflowSource
    status: WorkflowRunStatus
    history_expired: bool
    artifact_count: Annotated[int, Field(ge=0)]
    created_at: datetime
    updated_at: datetime


class WorkflowRunPage(StrictModel):
    items: list[WorkflowRun]
    next_cursor: str | None


class MoveWorkflow(StrictModel):
    project_id: ProjectId
```

`python/src/thoth_control_plane/infrastructure/workflow_run_store.py`:
```python
"""Workflow runs in PostgreSQL (editor migration 0012). Synchronous; callers use asyncio.to_thread."""

from __future__ import annotations

import base64
import logging
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import and_, create_engine, func, or_, select
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from thoth_control_plane.domain import Actor, ArtifactRef, WorkflowSummary
from thoth_control_plane.domain.workflow_runs import WorkflowRun
from thoth_control_plane.infrastructure.report_models import WorkflowReportRow
from thoth_control_plane.infrastructure.run_models import WorkflowRunRow

logger = logging.getLogger(__name__)

_REPORT_LABELS = {
    "source_report": "Source investigation report",
    "original_source_report": "Original source report",
    "source_attribution": "Source attribution",
    "content_set": "Content set",
}


class WorkflowRunsUnavailable(RuntimeError):
    """The database could not be reached or refused the statement."""


@dataclass(frozen=True)
class StoredRun:
    workflow_id: str
    project_id: str | None
    actor_type: str
    actor_id: str
    display_url: str
    platform: str
    status: str
    history_expired: bool
    summary: WorkflowSummary | None
    created_at: datetime
    updated_at: datetime

    def owned_by(self, actor: Actor) -> bool:
        return (self.actor_type, self.actor_id) == (actor.actor_type, actor.actor_id)

    def to_run(self) -> WorkflowRun:
        return WorkflowRun(
            workflow_id=self.workflow_id,
            project_id=self.project_id,
            source={"display_url": self.display_url, "platform": self.platform},
            status=self.status,
            history_expired=self.history_expired,
            artifact_count=len(self.summary.artifacts) if self.summary else 0,
            created_at=self.created_at,
            updated_at=self.updated_at,
        )

    def with_(self, **changes: Any) -> StoredRun:
        return replace(self, **changes)


def _stored(row: WorkflowRunRow) -> StoredRun:
    return StoredRun(
        workflow_id=row.workflow_id, project_id=row.project_id, actor_type=row.actor_type,
        actor_id=row.actor_id, display_url=row.display_url, platform=row.platform,
        status=row.status, history_expired=row.history_expired,
        summary=None if row.summary is None else WorkflowSummary.model_validate(row.summary),
        created_at=row.created_at, updated_at=row.updated_at,
    )


def _cursor(run: StoredRun) -> str:
    return base64.urlsafe_b64encode(f"{run.created_at.isoformat()}|{run.workflow_id}".encode()).decode()


def _decode(cursor: str) -> tuple[datetime, str]:
    created_at, workflow_id = base64.urlsafe_b64decode(cursor.encode()).decode().split("|", 1)
    return datetime.fromisoformat(created_at), workflow_id


class WorkflowRunStore:
    def __init__(self, engine: Engine, clock: Callable[[], datetime] = lambda: datetime.now(UTC)) -> None:
        self._sessions = sessionmaker(engine, expire_on_commit=False)
        self._clock = clock

    @classmethod
    def connect(cls, database_url: str) -> WorkflowRunStore:
        url = make_url(database_url).set(drivername="postgresql+psycopg")
        return cls(
            create_engine(
                url, pool_pre_ping=True, pool_size=2, max_overflow=2, hide_parameters=True,
                connect_args={"connect_timeout": 10},
            )
        )

    def _fail(self, error: Exception) -> WorkflowRunsUnavailable:
        logger.warning("workflow run store failed: %s", type(error).__name__)
        return WorkflowRunsUnavailable("workflow_runs_unavailable")

    def record_start(self, summary: WorkflowSummary, *, project_id: str | None, actor: Actor) -> None:
        now = self._clock()
        try:
            with self._sessions.begin() as session:
                row = session.get(WorkflowRunRow, summary.workflow_id)
                if row is None:
                    session.add(
                        WorkflowRunRow(
                            workflow_id=summary.workflow_id, project_id=project_id,
                            actor_type=actor.actor_type, actor_id=actor.actor_id,
                            display_url=str(summary.source.display_url),
                            platform=summary.source.platform, status=summary.status.value,
                            history_expired=False, summary=summary.model_dump(mode="json"),
                            created_at=now, updated_at=now,
                        )
                    )
                    return
                row.status = summary.status.value
                row.summary = summary.model_dump(mode="json")
                row.updated_at = now
        except SQLAlchemyError as error:
            raise self._fail(error) from None

    def page(
        self, *, project_id: str | None, unassigned: bool, actor: Actor, cursor: str | None, limit: int
    ) -> tuple[list[StoredRun], str | None]:
        query = select(WorkflowRunRow).where(
            WorkflowRunRow.actor_type == actor.actor_type, WorkflowRunRow.actor_id == actor.actor_id
        )
        query = query.where(
            WorkflowRunRow.project_id.is_(None) if unassigned else WorkflowRunRow.project_id == project_id
        )
        if cursor:
            created_at, workflow_id = _decode(cursor)
            query = query.where(
                or_(
                    WorkflowRunRow.created_at < created_at,
                    and_(WorkflowRunRow.created_at == created_at, WorkflowRunRow.workflow_id < workflow_id),
                )
            )
        query = query.order_by(WorkflowRunRow.created_at.desc(), WorkflowRunRow.workflow_id.desc()).limit(limit + 1)
        try:
            with self._sessions() as session:
                rows = [_stored(row) for row in session.scalars(query).all()]
        except SQLAlchemyError as error:
            raise self._fail(error) from None
        page = rows[:limit]
        return page, (_cursor(page[-1]) if len(rows) > limit else None)

    def get(self, workflow_id: str) -> StoredRun | None:
        try:
            with self._sessions() as session:
                row = session.get(WorkflowRunRow, workflow_id)
        except SQLAlchemyError as error:
            raise self._fail(error) from None
        return None if row is None else _stored(row)

    def settle(
        self, workflow_id: str, *, status: str, summary: WorkflowSummary | None, history_expired: bool
    ) -> None:
        try:
            with self._sessions.begin() as session:
                row = session.get(WorkflowRunRow, workflow_id)
                if row is None:
                    return
                row.status = status
                row.history_expired = history_expired
                if summary is not None:
                    row.summary = summary.model_dump(mode="json")
                row.updated_at = self._clock()
        except SQLAlchemyError as error:
            raise self._fail(error) from None

    def assign(self, workflow_id: str, project_id: str) -> StoredRun | None:
        try:
            with self._sessions.begin() as session:
                row = session.get(WorkflowRunRow, workflow_id)
                if row is None:
                    return None
                row.project_id = project_id
                row.updated_at = self._clock()
                return _stored(row)
        except SQLAlchemyError as error:
            raise self._fail(error) from None

    def insert_missing(self, run: StoredRun) -> bool:
        try:
            with self._sessions.begin() as session:
                if session.get(WorkflowRunRow, run.workflow_id) is not None:
                    return False
                session.add(
                    WorkflowRunRow(
                        workflow_id=run.workflow_id, project_id=run.project_id,
                        actor_type=run.actor_type, actor_id=run.actor_id,
                        display_url=run.display_url, platform=run.platform, status=run.status,
                        history_expired=run.history_expired,
                        summary=None if run.summary is None else run.summary.model_dump(mode="json"),
                        created_at=run.created_at, updated_at=run.updated_at,
                    )
                )
                return True
        except SQLAlchemyError as error:
            raise self._fail(error) from None

    def report_artifacts(self, workflow_id: str) -> list[ArtifactRef]:
        try:
            with self._sessions() as session:
                rows = session.scalars(
                    select(WorkflowReportRow)
                    .where(WorkflowReportRow.workflow_id == workflow_id)
                    .order_by(WorkflowReportRow.location)
                ).all()
        except SQLAlchemyError as error:
            raise self._fail(error) from None
        return [
            ArtifactRef(
                artifact_id=row.kind, kind=row.kind, label=_REPORT_LABELS.get(row.kind, row.kind),
                media_type="application/json", location=row.location,
                checksum=f"sha256:{row.sha256}", size_bytes=row.size_bytes,
            )
            for row in rows
        ]

    def source_report_rows(self) -> list[tuple[str, str, datetime]]:
        earliest = (
            select(WorkflowReportRow.workflow_id, func.min(WorkflowReportRow.created_at).label("first"))
            .group_by(WorkflowReportRow.workflow_id)
            .subquery()
        )
        query = (
            select(WorkflowReportRow.workflow_id, WorkflowReportRow.content, earliest.c.first)
            .join(earliest, earliest.c.workflow_id == WorkflowReportRow.workflow_id)
            .where(WorkflowReportRow.kind == "source_report")
            .order_by(WorkflowReportRow.workflow_id)
        )
        try:
            with self._sessions() as session:
                return [(w, c, f) for w, c, f in session.execute(query).all()]
        except SQLAlchemyError as error:
            raise self._fail(error) from None
```
`min()` over `UtcDateTime` returns a plain value on SQLite; when `first.tzinfo is None`, apply
`first.replace(tzinfo=UTC)` before returning.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `make test T=tests/infrastructure/test_workflow_run_store.py tests/domain`
Expected: PASS. The domain tests prove that `history_expired` broke no summary round-trip.

- [ ] **Step 5: Commit**

```bash
git add python/src/thoth_control_plane/domain/workflow_runs.py python/src/thoth_control_plane/domain/models.py python/src/thoth_control_plane/infrastructure/workflow_run_store.py python/tests/infrastructure/test_workflow_run_store.py
git commit -m "feat(runs): store workflow runs per project"
```

### Task 4: The gateway's `settle` call

**Files:**
- Modify: `python/src/thoth_control_plane/application/ports.py` (`RunLive`, `RunClosed`, `RunExpired`, `RunSettlement`, and `WorkflowGateway.settle`)
- Modify: `python/src/thoth_control_plane/application/workflows.py` (`UnavailableWorkflowGateway.settle`)
- Modify: `python/src/thoth_control_plane/infrastructure/temporal_gateway.py` (`settle`)
- Modify: `python/tests/conftest.py` (`InMemoryWorkflowGateway.settle`)
- Test: `python/tests/infrastructure/test_temporal_gateway_settle.py`

**Interfaces:**
- Produces:
  - `RunLive(summary: WorkflowSummary)`;
  - `RunClosed(summary: WorkflowSummary | None, status: str)`;
  - `RunExpired()`;
  - `async def settle(self, workflow_id: str) -> RunSettlement`.
- The in-memory gateway gains `settlements: dict[str, RunSettlement]` and
  `settle_error: Exception | None`.

- [ ] **Step 1: Write the failing test**

`python/tests/infrastructure/test_temporal_gateway_settle.py`:
```python
from datetime import UTC, datetime

import pytest
from temporalio.client import WorkflowExecutionStatus
from temporalio.service import RPCError, RPCStatusCode

from thoth_control_plane.application.ports import RunClosed, RunExpired, RunLive
from thoth_control_plane.domain import WorkflowSummary
from thoth_control_plane.infrastructure.temporal_gateway import TemporalWorkflowGateway

T0 = datetime(2026, 10, 18, tzinfo=UTC)
SUMMARY = WorkflowSummary(
    workflow_id="wf_a", status="succeeded", created_at=T0, updated_at=T0,
    source={"display_url": "https://example.test/p", "platform": "example"}, stages=[],
)


class Handle:
    def __init__(self, status=None, error=None):
        self.id, self._status, self._error = "wf_a", status, error

    async def describe(self):
        if self._error:
            raise self._error
        return type("D", (), {"status": self._status})()

    async def result(self):
        return SUMMARY

    async def query(self, query):
        return SUMMARY.model_copy(update={"status": "running"})


class Client:
    def __init__(self, handle):
        self.handle = handle

    def get_workflow_handle(self, workflow_id, *, result_type=None):
        return self.handle


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("handle", "expected"),
    [
        (Handle(WorkflowExecutionStatus.RUNNING), RunLive),
        (Handle(WorkflowExecutionStatus.COMPLETED), RunClosed),
        (Handle(error=RPCError("gone", RPCStatusCode.NOT_FOUND, b"")), RunExpired),
    ],
)
async def test_settle_maps_each_execution_state(handle, expected) -> None:
    outcome = await TemporalWorkflowGateway(Client(handle)).settle("wf_a")
    assert isinstance(outcome, expected)


@pytest.mark.asyncio
async def test_completed_reports_the_returned_summary_and_terminal_states_map() -> None:
    done = await TemporalWorkflowGateway(Client(Handle(WorkflowExecutionStatus.COMPLETED))).settle("wf_a")
    assert done == RunClosed(SUMMARY, "succeeded")
    failed = await TemporalWorkflowGateway(Client(Handle(WorkflowExecutionStatus.TERMINATED))).settle("wf_a")
    assert failed == RunClosed(None, "failed")
    cancelled = await TemporalWorkflowGateway(Client(Handle(WorkflowExecutionStatus.CANCELED))).settle("wf_a")
    assert cancelled == RunClosed(None, "cancelled")
```

- [ ] **Step 2: Run it to verify it fails**

Run: `make test T=tests/infrastructure/test_temporal_gateway_settle.py`
Expected: FAIL with `cannot import name 'RunClosed'`.

- [ ] **Step 3: Implement**

In `application/ports.py`, add near the top, after the imports (add
`from dataclasses import dataclass`):
```python
@dataclass(frozen=True)
class RunLive:
    summary: WorkflowSummary


@dataclass(frozen=True)
class RunClosed:
    summary: WorkflowSummary | None
    status: str


@dataclass(frozen=True)
class RunExpired:
    pass


RunSettlement = RunLive | RunClosed | RunExpired
```
In `class WorkflowGateway(Protocol)`, add
`async def settle(self, workflow_id: str) -> RunSettlement: ...`.

In `application/workflows.py`, `UnavailableWorkflowGateway`:
```python
    async def settle(self, workflow_id: str) -> RunSettlement:
        raise WorkflowNotReady
```
Import `RunSettlement` from `application.ports`.

In `temporal_gateway.py`, import `WorkflowExecutionStatus` from `temporalio.client` and
`RunClosed, RunExpired, RunLive, RunSettlement` from `thoth_control_plane.application.ports`.
Then add to `TemporalWorkflowGateway`:
```python
    async def settle(self, workflow_id: str) -> RunSettlement:
        """Read a run's state without its owner query, so a closed run is never replayed (P4)."""
        handle = self._client.get_workflow_handle(workflow_id, result_type=WorkflowSummary)
        try:
            description = await handle.describe()
        except RPCError as error:
            if error.status == RPCStatusCode.NOT_FOUND:
                return RunExpired()
            raise WorkflowNotReady() from error
        if description.status == WorkflowExecutionStatus.RUNNING:
            return RunLive(await _query(handle, SourceInvestigationWorkflow.summary))
        if description.status == WorkflowExecutionStatus.COMPLETED:
            summary = await handle.result()
            return RunClosed(summary, summary.status.value)
        if description.status == WorkflowExecutionStatus.CANCELED:
            return RunClosed(None, "cancelled")
        return RunClosed(None, "failed")
```

In `tests/conftest.py`, add to `InMemoryWorkflowGateway.__init__`:
```python
        self.settlements: dict[str, RunSettlement] = {}
        self.settle_error: Exception | None = None
```
and add this method (import `RunExpired, RunLive, RunSettlement` from
`thoth_control_plane.application.ports`):
```python
    async def settle(self, workflow_id: str) -> RunSettlement:
        if self.settle_error is not None:
            raise self.settle_error
        if workflow_id in self.settlements:
            return self.settlements[workflow_id]
        if workflow_id in self.workflows:
            return RunLive(self.workflows[workflow_id])
        return RunExpired()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `make test T=tests/infrastructure/test_temporal_gateway_settle.py tests/api/test_workflows.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add python/src/thoth_control_plane/application/ports.py python/src/thoth_control_plane/application/workflows.py python/src/thoth_control_plane/infrastructure/temporal_gateway.py python/tests/conftest.py python/tests/infrastructure/test_temporal_gateway_settle.py
git commit -m "feat(workflows): settle a run from Temporal describe and result"
```

### Task 5: The workflow run service and its routes

**Files:**
- Create: `python/src/thoth_control_plane/application/workflow_runs.py`
- Create: `python/src/thoth_control_plane/api/routes/workflow_runs.py`
- Modify: `python/src/thoth_control_plane/api/routes/workflows.py`, so that `create_workflow`,
  `get_workflow` and `download_workflow_artifact` go through `WorkflowRunService`
- Modify: `python/src/thoth_control_plane/api/app.py`:
  - a `workflow_run_store` param and `app.state.workflow_run_store`;
  - the router;
  - map `WorkflowRunsUnavailable` to 503 `workflow_runs_unavailable`;
  - map `ProjectNotFound` to 404 `project_not_found`.
- Test: `python/tests/api/test_workflow_runs.py`

**Interfaces:**
- Consumes:
  - `WorkflowRunStore`, `StoredRun` and `UNSETTLED` (Task 3);
  - `ProjectStore` (Task 2);
  - `RunLive`, `RunClosed` and `RunExpired` (Task 4);
  - `WorkflowService` (existing).
- Produces: `WorkflowRunService(runs, projects, workflows, gateway)` with:
  - `start(project_id: str | None, request, *, actor, idempotency_key) -> WorkflowSummary`;
  - `page(*, project_id: str | None, unassigned: bool, actor, cursor, limit) -> WorkflowRunPage`;
  - `get(workflow_id, *, actor) -> WorkflowSummary`;
  - `get_artifact(workflow_id, artifact_id, *, actor) -> ArtifactRef`;
  - `assign(workflow_id, project_id, *, actor) -> WorkflowRun`.
  It also exports `ProjectNotFound` and `SETTLE_LIMIT = 20`.

- [ ] **Step 1: Write the failing tests**

`python/tests/api/test_workflow_runs.py`:
```python
from datetime import UTC, datetime

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from thoth_control_plane.api import create_app
from thoth_control_plane.application import WorkflowNotReady
from thoth_control_plane.application.ports import RunClosed, RunExpired
from thoth_control_plane.config import Settings
from thoth_control_plane.infrastructure import run_models  # noqa: F401
from thoth_control_plane.infrastructure.project_store import ProjectStore
from thoth_control_plane.infrastructure.report_store import ReportStore
from thoth_control_plane.infrastructure.source_account_models import Base
from thoth_control_plane.infrastructure.workflow_run_store import (
    StoredRun,
    WorkflowRunStore,
    WorkflowRunsUnavailable,
)

AUTH = {"Authorization": "Bearer test-key"}
REQUEST = {
    "source": {"url": "https://www.tiktok.com/@a/video/1", "intent": "identify_original"},
    "style": {"preset_id": "news-vertical"},
    "output": {"format": "vertical_video", "language": "id"},
    "review": {"require_publish_approval": True},
}


@pytest.fixture
def stores():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return ProjectStore(engine), WorkflowRunStore(engine), ReportStore(engine)


@pytest_asyncio.fixture
async def api(gateway, stores):
    projects, runs, reports = stores
    app = create_app(
        Settings(THOTH_CONTROL_PLANE_API_KEY="test-key"), gateway,
        project_store=projects, workflow_run_store=runs, report_store=reports,
    )
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield client


async def start(api, project_id: str, key: str = "k1"):
    return await api.post(
        f"/api/v1/projects/{project_id}/workflows", json=REQUEST, headers={**AUTH, "Idempotency-Key": key}
    )


@pytest.mark.asyncio
async def test_a_project_start_is_listed_under_its_project(api, stores) -> None:
    project = stores[0].create("News")
    assert (await start(api, project.project_id)).status_code == 202
    page = (await api.get(f"/api/v1/projects/{project.project_id}/workflows", headers=AUTH)).json()
    assert [r["workflow_id"] for r in page["items"]] == ["wf_001"] and page["next_cursor"] is None


@pytest.mark.asyncio
async def test_an_unknown_project_never_starts(api, gateway) -> None:
    response = await start(api, "missing")
    assert response.status_code == 404 and response.json() == {"detail": "project_not_found"}
    assert gateway.workflows == {}


@pytest.mark.asyncio
async def test_the_legacy_start_is_unassigned_and_can_be_moved(api, stores) -> None:
    await api.post("/api/v1/workflows", json=REQUEST, headers={**AUTH, "Idempotency-Key": "k"})
    loose = (await api.get("/api/v1/workflows?unassigned=true", headers=AUTH)).json()["items"]
    assert [r["workflow_id"] for r in loose] == ["wf_001"]
    project = stores[0].create("News")
    moved = await api.patch("/api/v1/workflows/wf_001", json={"project_id": project.project_id}, headers=AUTH)
    assert moved.status_code == 200 and moved.json()["project_id"] == project.project_id
    assert (await api.get("/api/v1/workflows?unassigned=false", headers=AUTH)).status_code == 422


@pytest.mark.asyncio
async def test_a_retried_start_after_a_row_failure_lands_the_row(api, stores, monkeypatch) -> None:
    project = stores[0].create("News")
    runs = stores[1]
    original = runs.record_start
    calls = {"n": 0}

    def flaky(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise WorkflowRunsUnavailable("workflow_runs_unavailable")
        return original(*args, **kwargs)

    monkeypatch.setattr(runs, "record_start", flaky)
    first = await start(api, project.project_id, "same")
    assert first.status_code == 503 and first.json() == {"detail": "workflow_runs_unavailable"}
    assert (await start(api, project.project_id, "same")).status_code == 202
    assert runs.get("wf_001") is not None


@pytest.mark.asyncio
async def test_listing_settles_closed_and_expired_runs(api, stores, gateway) -> None:
    project = stores[0].create("News")
    await start(api, project.project_id)
    gateway.settlements["wf_001"] = RunClosed(None, "cancelled")
    item = (await api.get(f"/api/v1/projects/{project.project_id}/workflows", headers=AUTH)).json()["items"][0]
    assert item["status"] == "cancelled"
    t0 = datetime(2026, 9, 1, tzinfo=UTC)
    stores[1].insert_missing(StoredRun("wf_old", project.project_id, "user", "owner", "https://x.test/v", "tiktok", "unknown", False, None, t0, t0))
    stores[2].put("reports/wf_old/source-report.json", "source_report", b"{}")
    gateway.settlements["wf_old"] = RunExpired()
    items = (await api.get(f"/api/v1/projects/{project.project_id}/workflows", headers=AUTH)).json()["items"]
    old = next(i for i in items if i["workflow_id"] == "wf_old")
    assert old["history_expired"] is True and old["status"] == "unknown" and old["artifact_count"] == 1


@pytest.mark.asyncio
async def test_a_temporal_outage_still_lists_the_stored_rows(api, stores, gateway) -> None:
    project = stores[0].create("News")
    await start(api, project.project_id)
    gateway.settle_error = WorkflowNotReady()
    response = await api.get(f"/api/v1/projects/{project.project_id}/workflows", headers=AUTH)
    assert response.status_code == 200 and response.json()["items"][0]["status"] == "queued"


@pytest.mark.asyncio
async def test_an_expired_workflow_detail_answers_from_the_store(api, stores) -> None:
    t0 = datetime(2026, 9, 1, tzinfo=UTC)
    stores[1].insert_missing(StoredRun("wf_old", None, "user", "owner", "https://x.test/v", "tiktok", "unknown", True, None, t0, t0))
    stores[2].put("reports/wf_old/source-report.json", "source_report", b"{}")
    body = (await api.get("/api/v1/workflows/wf_old", headers=AUTH)).json()
    assert body["history_expired"] is True and body["status"] == "succeeded"
    assert [a["artifact_id"] for a in body["artifacts"]] == ["source_report"]
    report = await api.get("/api/v1/workflows/wf_old/artifacts/source_report", headers=AUTH)
    assert report.status_code == 200 and report.content == b"{}"
```

- [ ] **Step 2: Run them to verify they fail**

Run: `make test T=tests/api/test_workflow_runs.py`
Expected: FAIL. `create_app()` rejects the unexpected `workflow_run_store` keyword.

- [ ] **Step 3: Implement the service**

`python/src/thoth_control_plane/application/workflow_runs.py`:
```python
"""Record, list, settle, and move workflow runs (spec 2026-10-18, sections 3.3 and 3.4)."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from thoth_control_plane.application.ports import RunClosed, RunExpired, RunLive
from thoth_control_plane.application.workflows import (
    ArtifactNotFound,
    WorkflowApplicationError,
    WorkflowNotFound,
    WorkflowNotReady,
    WorkflowService,
)
from thoth_control_plane.domain import Actor, ArtifactRef, WorkflowRequest, WorkflowSummary
from thoth_control_plane.domain.workflow_runs import UNSETTLED, WorkflowRun, WorkflowRunPage
from thoth_control_plane.infrastructure.workflow_run_store import StoredRun, WorkflowRunsUnavailable

logger = logging.getLogger(__name__)
SETTLE_LIMIT = 20


class ProjectNotFound(WorkflowApplicationError):
    default_detail = "project_not_found"


class WorkflowRunService:
    def __init__(self, runs: Any, projects: Any, workflows: WorkflowService, gateway: Any) -> None:
        self._runs, self._projects, self._workflows, self._gateway = runs, projects, workflows, gateway

    def _store(self) -> Any:
        if self._runs is None:
            raise WorkflowRunsUnavailable("workflow_runs_unavailable")
        return self._runs

    async def _require_project(self, project_id: str) -> None:
        if self._projects is None:
            raise WorkflowRunsUnavailable("workflow_runs_unavailable")
        if await asyncio.to_thread(self._projects.get, project_id) is None:
            raise ProjectNotFound

    async def start(
        self, project_id: str | None, request: WorkflowRequest, *, actor: Actor, idempotency_key: str
    ) -> WorkflowSummary:
        if project_id is not None:
            await self._require_project(project_id)
        summary = await self._workflows.start(request, actor=actor, idempotency_key=idempotency_key)
        if self._runs is None:
            if project_id is not None:
                raise WorkflowRunsUnavailable("workflow_runs_unavailable")
            return summary
        await asyncio.to_thread(self._runs.record_start, summary, project_id=project_id, actor=actor)
        return summary

    async def page(
        self, *, project_id: str | None, unassigned: bool, actor: Actor, cursor: str | None, limit: int
    ) -> WorkflowRunPage:
        store = self._store()
        if project_id is not None:
            await self._require_project(project_id)
        rows, next_cursor = await asyncio.to_thread(
            store.page, project_id=project_id, unassigned=unassigned, actor=actor, cursor=cursor, limit=limit
        )
        due = [r for r in rows if r.status in UNSETTLED and not r.history_expired][:SETTLE_LIMIT]
        settled = {r.workflow_id: r for r in await asyncio.gather(*(self._settle(r) for r in due))}
        return WorkflowRunPage(
            items=[settled.get(r.workflow_id, r).to_run() for r in rows], next_cursor=next_cursor
        )

    async def _settle(self, run: StoredRun) -> StoredRun:
        try:
            outcome = await self._gateway.settle(run.workflow_id)
        except (WorkflowNotReady, WorkflowNotFound) as error:
            logger.warning("run settle skipped workflow_id=%s reason=%s", run.workflow_id, type(error).__name__)
            return run
        if isinstance(outcome, RunLive):
            updated = run.with_(status=outcome.summary.status.value, summary=outcome.summary)
        elif isinstance(outcome, RunClosed):
            updated = run.with_(status=outcome.status, summary=outcome.summary or run.summary)
        else:
            summary = run.summary or await self._synthesized(run)
            updated = run.with_(history_expired=True, summary=summary)
            assert isinstance(outcome, RunExpired)
        try:
            await asyncio.to_thread(
                self._store().settle, run.workflow_id, status=updated.status,
                summary=updated.summary, history_expired=updated.history_expired,
            )
        except WorkflowRunsUnavailable:
            logger.warning("run settle not saved workflow_id=%s", run.workflow_id)
        return updated

    async def _synthesized(self, run: StoredRun) -> WorkflowSummary:
        """Ruling P3: WorkflowSummary has no `unknown`; the run list keeps it."""
        artifacts: list[ArtifactRef] = await asyncio.to_thread(self._store().report_artifacts, run.workflow_id)
        return WorkflowSummary(
            workflow_id=run.workflow_id, status="succeeded", created_at=run.created_at,
            updated_at=run.updated_at, source={"display_url": run.display_url, "platform": run.platform},
            stages=[], artifacts=artifacts, history_expired=True,
        )

    async def get(self, workflow_id: str, *, actor: Actor) -> WorkflowSummary:
        try:
            summary = await self._workflows.get(workflow_id, actor=actor)
        except WorkflowNotFound:
            if self._runs is None:
                raise
            run = await asyncio.to_thread(self._runs.get, workflow_id)
            if run is None or not run.owned_by(actor):
                raise
            summary = run.summary or await self._synthesized(run)
            return summary.model_copy(update={"history_expired": True})
        if self._runs is not None:
            try:
                await asyncio.to_thread(
                    self._runs.settle, workflow_id, status=summary.status.value, summary=summary, history_expired=False
                )
            except WorkflowRunsUnavailable:
                logger.warning("run summary not saved workflow_id=%s", workflow_id)
        return summary

    async def get_artifact(self, workflow_id: str, artifact_id: str, *, actor: Actor) -> ArtifactRef:
        summary = await self.get(workflow_id, actor=actor)
        for artifact in summary.artifacts:
            if artifact.artifact_id == artifact_id:
                return artifact
        raise ArtifactNotFound

    async def assign(self, workflow_id: str, project_id: str, *, actor: Actor) -> WorkflowRun:
        store = self._store()
        await self._require_project(project_id)
        run = await asyncio.to_thread(store.get, workflow_id)
        if run is None or not run.owned_by(actor):
            raise WorkflowNotFound
        moved = await asyncio.to_thread(store.assign, workflow_id, project_id)
        if moved is None:
            raise WorkflowNotFound
        return moved.to_run()
```
Export `WorkflowRunService` and `ProjectNotFound` from `application/__init__.py`, next to
`WorkflowService`.

- [ ] **Step 4: Implement the routes and the wiring**

`python/src/thoth_control_plane/api/routes/workflow_runs.py`:
```python
"""Workflow runs per project: start, list, move."""

from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status

from thoth_control_plane.api.dependencies import current_actor
from thoth_control_plane.application import Actor, WorkflowRequest, WorkflowRunService, WorkflowSummary
from thoth_control_plane.domain.workflow_runs import MoveWorkflow, WorkflowRun, WorkflowRunPage

router = APIRouter()


def get_run_service(request: Request) -> WorkflowRunService:
    state = request.app.state
    return WorkflowRunService(
        state.workflow_run_store, state.project_store, state.workflow_service, state.workflow_gateway
    )


Limit = Annotated[int, Query(ge=1, le=50)]


@router.post("/projects/{project_id}/workflows", response_model=WorkflowSummary, status_code=status.HTTP_202_ACCEPTED)
async def start_project_workflow(
    project_id: str,
    request: WorkflowRequest,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1)],
    actor: Annotated[Actor, Depends(current_actor)],
    service: Annotated[WorkflowRunService, Depends(get_run_service)],
) -> WorkflowSummary:
    return await service.start(project_id, request, actor=actor, idempotency_key=idempotency_key)


@router.get("/projects/{project_id}/workflows", response_model=WorkflowRunPage)
async def list_project_workflows(
    project_id: str,
    actor: Annotated[Actor, Depends(current_actor)],
    service: Annotated[WorkflowRunService, Depends(get_run_service)],
    cursor: str | None = None,
    limit: Limit = 20,
) -> WorkflowRunPage:
    return await service.page(project_id=project_id, unassigned=False, actor=actor, cursor=cursor, limit=limit)


@router.get("/workflows", response_model=WorkflowRunPage)
async def list_unassigned_workflows(
    actor: Annotated[Actor, Depends(current_actor)],
    service: Annotated[WorkflowRunService, Depends(get_run_service)],
    unassigned: bool = Query(...),
    cursor: str | None = None,
    limit: Limit = 20,
) -> WorkflowRunPage:
    if not unassigned:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="unassigned_must_be_true")
    return await service.page(project_id=None, unassigned=True, actor=actor, cursor=cursor, limit=limit)


@router.patch("/workflows/{workflow_id}", response_model=WorkflowRun)
async def move_workflow(
    workflow_id: str,
    body: MoveWorkflow,
    actor: Annotated[Actor, Depends(current_actor)],
    service: Annotated[WorkflowRunService, Depends(get_run_service)],
) -> WorkflowRun:
    return await service.assign(workflow_id, body.project_id, actor=actor)
```

In `routes/workflows.py`:
- import `get_run_service` from `routes.workflow_runs` and `WorkflowRunService` from
  `application`;
- `create_workflow` → `return await runs.start(None, request, actor=actor, idempotency_key=idempotency_key)`,
  with the dependency `runs: Annotated[WorkflowRunService, Depends(get_run_service)]` in place
  of `service`;
- `get_workflow` → `return await runs.get(workflow_id, actor=actor)`;
- `download_workflow_artifact` → `artifact = await runs.get_artifact(workflow_id, artifact_id, actor=actor)`.
  The rest of that route changes in Task 7.

In `api/app.py`:
- add the `workflow_run_store: WorkflowRunStore | None = None` parameter;
- add, after the `project_store` block:
  ```python
  if workflow_run_store is None and settings.THOTH_EDITOR_DATABASE_URL is not None:
      workflow_run_store = WorkflowRunStore.connect(settings.THOTH_EDITOR_DATABASE_URL.get_secret_value())
  app.state.workflow_run_store = workflow_run_store
  ```
- add `ProjectNotFound: status.HTTP_404_NOT_FOUND` to `exception_statuses`. Its `str()` is
  `project_not_found`, so the generic handler returns `{"detail": "project_not_found"}`;
- add a handler for `WorkflowRunsUnavailable` returning 503 `{"detail": "workflow_runs_unavailable"}`;
- include `workflow_runs.router` with the same prefix and dependencies as the workflows router,
  **before** the workflows router, so `GET /workflows` is not shadowed.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `make test T=tests/api/test_workflow_runs.py tests/api/test_workflows.py tests/application`
Expected: PASS. The existing workflow tests run with no run store and keep their behaviour.

- [ ] **Step 6: Commit**

```bash
git add python/src/thoth_control_plane/application/workflow_runs.py python/src/thoth_control_plane/application/__init__.py python/src/thoth_control_plane/api/routes/workflow_runs.py python/src/thoth_control_plane/api/routes/workflows.py python/src/thoth_control_plane/api/app.py python/tests/api/test_workflow_runs.py
git commit -m "feat(runs): start, list, settle, and move workflow runs per project"
```

### Task 6: Backfill and the deploy step

**Files:**
- Create: `python/src/thoth_control_plane/operations/run_backfill.py`
- Modify: `python/src/thoth_control_plane/cli.py` (`workflows backfill`, under the existing `workflow_app`)
- Modify: `scripts/ops/deploy-stage1.sh` (the `backfill-runs` step after `migrate`)
- Test: `python/tests/operations/test_run_backfill.py`

**Interfaces:**
- Consumes: `WorkflowRunStore.source_report_rows`, `insert_missing`, `StoredRun` (Task 3).
- Produces: `backfill_runs(store) -> BackfillCounts(inserted, present, invalid)`.

- [ ] **Step 1: Write the failing test**

`python/tests/operations/test_run_backfill.py`:
```python
import json

from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from thoth_control_plane.infrastructure import run_models  # noqa: F401
from thoth_control_plane.infrastructure.report_store import ReportStore
from thoth_control_plane.infrastructure.source_account_models import Base
from thoth_control_plane.infrastructure.workflow_run_store import WorkflowRunStore
from thoth_control_plane.operations.run_backfill import backfill_runs

GOOD = "wf_" + "a" * 24


def report(url: str, platform: str = "tiktok") -> bytes:
    return json.dumps({"source": {"canonical_url": url, "platform": platform}}).encode()


def test_backfill_inserts_once_strips_queries_and_counts_invalid() -> None:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    reports, runs = ReportStore(engine), WorkflowRunStore(engine)
    reports.put(f"reports/{GOOD}/source-report.json", "source_report", report("https://x.test/v/1?sig=s#f"))
    reports.put("reports/wf_" + "b" * 24 + "/source-report.json", "source_report", b'{"source": {}}')
    reports.put("reports/wf_test/source-report.json", "source_report", report("https://x.test/v/2"))
    assert backfill_runs(runs) == (1, 0, 1)
    stored = runs.get(GOOD)
    assert stored is not None and stored.display_url == "https://x.test/v/1" and stored.status == "unknown"
    assert stored.project_id is None and (stored.actor_type, stored.actor_id) == ("user", "owner")
    assert backfill_runs(runs) == (0, 1, 1)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `make test T=tests/operations/test_run_backfill.py`
Expected: FAIL with `No module named ...run_backfill`.

- [ ] **Step 3: Implement**

`python/src/thoth_control_plane/operations/run_backfill.py`:
```python
"""One run row per workflow that already has a source report (spec 2026-10-18, section 3.5)."""

from __future__ import annotations

import json
import re
from typing import NamedTuple
from urllib.parse import urlsplit

from pydantic import ValidationError

from thoth_control_plane.domain.models import WorkflowSource
from thoth_control_plane.infrastructure.workflow_run_store import StoredRun, WorkflowRunStore

_WORKFLOW = re.compile(r"^wf_[0-9a-f]{24}$")


class BackfillCounts(NamedTuple):
    inserted: int
    present: int
    invalid: int


def backfill_runs(store: WorkflowRunStore) -> BackfillCounts:
    inserted = present = invalid = 0
    for workflow_id, content, first_seen in store.source_report_rows():
        if not _WORKFLOW.fullmatch(workflow_id):
            continue
        try:
            source = json.loads(content)["source"]
            display_url = urlsplit(source["canonical_url"])._replace(query="", fragment="").geturl()
            checked = WorkflowSource(display_url=display_url, platform=source["platform"])
        except (KeyError, TypeError, ValueError, ValidationError):
            invalid += 1
            continue
        run = StoredRun(
            workflow_id=workflow_id, project_id=None, actor_type="user", actor_id="owner",
            display_url=str(checked.display_url), platform=checked.platform, status="unknown",
            history_expired=False, summary=None, created_at=first_seen, updated_at=first_seen,
        )
        if store.insert_missing(run):
            inserted += 1
        else:
            present += 1
    return BackfillCounts(inserted, present, invalid)
```
`str(HttpUrl)` can add a trailing slash to a bare host. The test URL has a path, so it is
unaffected; keep `str(checked.display_url)` as is.

In `cli.py`:
```python
@workflow_app.command("backfill")
def workflows_backfill() -> None:
    """Create run rows for workflows that already have reports; idempotent; counts only."""
    database_url = Settings().THOTH_EDITOR_DATABASE_URL
    if database_url is None:
        raise typer.BadParameter("THOTH_EDITOR_DATABASE_URL must be configured")
    try:
        counts = backfill_runs(WorkflowRunStore.connect(database_url.get_secret_value()))
    except WorkflowRunsUnavailable:
        typer.echo("workflow run store unavailable")
        raise typer.Exit(1) from None
    typer.echo(f"inserted={counts.inserted} present={counts.present} invalid={counts.invalid}")
```
Import `backfill_runs`, `WorkflowRunStore` and `WorkflowRunsUnavailable` at the top of `cli.py`.

In `scripts/ops/deploy-stage1.sh`, directly after the `migrate` step's line, add:
```bash
step backfill-runs
"${compose[@]}" run --rm --no-deps api thoth-control workflow backfill 2>&1 | tail -1
```
The parent Typer group is `workflow` (`app.add_typer(workflow_app, name="workflow")`).

- [ ] **Step 4: Run the test to verify it passes**

Run: `make test T=tests/operations/test_run_backfill.py`
Expected: PASS. Then run `bash -n scripts/ops/deploy-stage1.sh` and expect exit 0.

- [ ] **Step 5: Commit**

```bash
git add python/src/thoth_control_plane/operations/run_backfill.py python/src/thoth_control_plane/cli.py scripts/ops/deploy-stage1.sh python/tests/operations/test_run_backfill.py
git commit -m "feat(runs): backfill run rows from stored reports on deploy"
```

### Task 7: Workflow media downloads from the store

**Files:**
- Modify: `python/src/thoth_control_plane/api/routes/workflows.py` (the non-report branch of `download_workflow_artifact`)
- Test: `python/tests/api/test_workflow_runs.py` (append)

**Interfaces:**
- Consumes: `app.state.media_store` (`size`, `open_range`); `ranged_response` (`api/ranged.py`).

- [ ] **Step 1: Write the failing tests**

Append to `python/tests/api/test_workflow_runs.py`:
```python
@pytest.mark.asyncio
async def test_media_artifacts_stream_from_the_store_with_ranges(gateway, stores, tmp_path) -> None:
    from thoth_control_plane.domain import ArtifactRef

    settings = Settings(THOTH_CONTROL_PLANE_API_KEY="test-key", THOTH_CONTROL_PLANE_ARTIFACT_ROOT=str(tmp_path))
    projects, runs, reports = stores
    app = create_app(settings, gateway, project_store=projects, workflow_run_store=runs, report_store=reports)
    clip = tmp_path / "reports" / "wf_001" / "footage" / "clip.mp4"
    clip.parent.mkdir(parents=True)
    clip.write_bytes(b"0123456789")
    await gateway.start(type("R", (), {"source": type("S", (), {"url": "https://x.test/v"})()})(), actor=None, idempotency_key="k")
    gateway.workflows["wf_001"] = gateway.workflows["wf_001"].model_copy(update={"artifacts": [
        ArtifactRef(artifact_id="clip", kind="footage", label="Clip", media_type="video/mp4", location="reports/wf_001/footage/clip.mp4"),
        ArtifactRef(artifact_id="gone", kind="footage", label="Gone", media_type="video/mp4", location="reports/wf_001/footage/gone.mp4"),
    ]})
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        whole = await client.get("/api/v1/workflows/wf_001/artifacts/clip", headers=AUTH)
        part = await client.get("/api/v1/workflows/wf_001/artifacts/clip", headers={**AUTH, "Range": "bytes=2-4"})
        missing = await client.get("/api/v1/workflows/wf_001/artifacts/gone", headers=AUTH)
    assert whole.status_code == 200 and whole.content == b"0123456789"
    assert part.status_code == 206 and part.content == b"234"
    assert missing.status_code == 404


@pytest.mark.asyncio
async def test_a_store_outage_answers_503(gateway, stores, monkeypatch) -> None:
    from thoth_control_plane.domain import ArtifactRef
    from thoth_control_plane.infrastructure.media_store import MediaStoreUnavailable

    projects, runs, reports = stores
    app = create_app(Settings(THOTH_CONTROL_PLANE_API_KEY="test-key"), gateway, project_store=projects, workflow_run_store=runs, report_store=reports)

    def down(location):
        raise MediaStoreUnavailable("media_store_unavailable")

    monkeypatch.setattr(app.state.media_store, "size", down)
    await gateway.start(type("R", (), {"source": type("S", (), {"url": "https://x.test/v"})()})(), actor=None, idempotency_key="k")
    gateway.workflows["wf_001"] = gateway.workflows["wf_001"].model_copy(update={"artifacts": [
        ArtifactRef(artifact_id="clip", kind="footage", label="Clip", media_type="video/mp4", location="reports/wf_001/footage/clip.mp4"),
    ]})
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/workflows/wf_001/artifacts/clip", headers=AUTH)
    assert response.status_code == 503
```
`InMemoryWorkflowGateway.start` reads only `request.source.url`; the throwaway objects above
satisfy it. If `actor=None` trips `self.actors.append`, pass
`Actor(actor_id="owner", actor_type="user")` instead.

- [ ] **Step 2: Run them to verify they fail**

Run: `make test T=tests/api/test_workflow_runs.py -k "store"`
Expected: FAIL. The first test gets 404 or 500 from the local `FileResponse` branch, which
returns no ranges; the second does not get 503.

- [ ] **Step 3: Implement**

In `download_workflow_artifact`, replace everything after the `if artifact.kind in REPORT_KINDS:`
block (the `artifact_root` and `FileResponse` lines) with:
```python
    media = request.app.state.media_store
    try:
        size = await asyncio.to_thread(media.size, artifact.location)
    except MediaUnavailable:
        raise ArtifactNotFound from None
    except MediaStoreUnavailable as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="media_store_unavailable"
        ) from error
    suffix = PurePosixPath(artifact.location).suffix
    return ranged_response(
        size=size,
        read=lambda start, end: media.open_range(artifact.location, start, end),
        media_type=artifact.media_type,
        range_header=request.headers.get("range"),
        headers={"Content-Disposition": f'attachment; filename="{artifact.artifact_id}{suffix}"'},
    )
```
- Imports: `from pathlib import PurePosixPath`; `from thoth_control_plane.api.ranged import ranged_response`;
  `from thoth_control_plane.infrastructure.media_store import MediaStoreUnavailable, MediaUnavailable`.
- Remove the now unused `FileResponse` and `Path` imports if nothing else uses them.
- Keep `response_class=FileResponse` in the decorator only if `test_openapi_contract.py` pins
  it; otherwise change it to `Response`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `make test T=tests/api/test_workflow_runs.py tests/api/test_workflows.py tests/api/test_openapi_contract.py`
Expected: PASS. Existing download tests in `test_workflows.py` that write files under the
artifact root keep passing, because `build_media_store` falls back to a `LocalMediaStore` on
that root. A test whose location lacks an allowed prefix (`reports`, `uploads`, `renders`,
`work` or `archive`) now gets 404; change its location to `reports/<id>/...`.

- [ ] **Step 5: Commit**

```bash
git add python/src/thoth_control_plane/api/routes/workflows.py python/tests/api/test_workflow_runs.py python/tests/api/test_workflows.py
git commit -m "fix(workflows): serve media artifacts from the store with ranges"
```

### Task 8: Studio documents per project

**Files:**
- Modify: `python/src/thoth_control_plane/application/ports.py` (`EditDocumentRepository.list_documents`)
- Modify: `python/src/thoth_control_plane/infrastructure/editor_repository.py` (`PostgresEditDocumentRepository.list_documents`)
- Modify: `python/src/thoth_control_plane/application/edit_documents.py` (`EditDocumentService.list_documents`)
- Modify: `python/src/thoth_control_plane/api/routes/edit_documents.py` (the `GET /projects/{project_id}/edit-documents` route, declared before the `{document_id}` route)
- Create: `python/src/thoth_control_plane/domain/edit_document_list.py`
- Test: `python/tests/domain/test_edit_document_list.py`, `python/tests/api/test_edit_documents.py` (append)

**Interfaces:**
- Produces:
  - `EditDocumentListItem(document_id, revision, updated_at, label, imported)` and
    `EditDocumentListPage(items, next_cursor)`;
  - `document_label(document_json: dict) -> str`;
  - repository `async list_documents(*, project_id, limit, cursor) -> EditDocumentListPage`.

- [ ] **Step 1: Write the failing tests**

`python/tests/domain/test_edit_document_list.py`:
```python
from thoth_control_plane.domain.edit_document_list import document_label


def test_the_label_is_the_first_non_empty_text_heading() -> None:
    doc = {"clips": [{"kind": "video"}, {"kind": "text", "heading": "  "}, {"kind": "text", "heading": " Kucing buka kulkas "}]}
    assert document_label(doc) == "Kucing buka kulkas"


def test_no_heading_is_untitled_and_long_headings_are_cut() -> None:
    assert document_label({"clips": []}) == "Untitled draft"
    assert len(document_label({"clips": [{"kind": "text", "heading": "x" * 300}]})) == 120
```

Append to `python/tests/api/test_edit_documents.py`. Add a `list_documents` method to
`MemoryEditDocumentRepository`:
```python
    async def list_documents(self, *, project_id: str, limit: int, cursor: str | None):
        from thoth_control_plane.domain.edit_document_list import (
            EditDocumentListItem,
            EditDocumentListPage,
            document_label,
        )

        items = [
            EditDocumentListItem(
                document_id=d.document_id, revision=d.revision,
                updated_at="2026-10-18T00:00:00Z",
                label=document_label(d.model_dump(mode="json")), imported=False,
            )
            for (p, _), d in self.documents.items() if p == project_id
        ]
        return EditDocumentListPage(items=items[:limit], next_cursor=None)
```
Then add a test that inserts one document through the existing helper used by the other tests
in this file, calls `GET /api/v1/projects/<that project>/edit-documents`, and asserts:
- status 200;
- `items[0]["document_id"]` equals the document's ID;
- `items[0]["label"]` equals its first text clip's heading;
- `limit=0` answers 422.

- [ ] **Step 2: Run them to verify they fail**

Run: `make test T=tests/domain/test_edit_document_list.py tests/api/test_edit_documents.py`
Expected: FAIL with `No module named ...edit_document_list` and a 404 or 405 on the new route.

- [ ] **Step 3: Implement**

`python/src/thoth_control_plane/domain/edit_document_list.py`:
```python
"""A project's Studio documents, newest revision first (spec 2026-10-18, section 3.6)."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from pydantic import Field

from thoth_control_plane.domain.models import OpaqueId, StrictModel


class EditDocumentListItem(StrictModel):
    document_id: OpaqueId
    revision: Annotated[int, Field(gt=0)]
    updated_at: datetime
    label: Annotated[str, Field(min_length=1, max_length=120)]
    imported: bool


class EditDocumentListPage(StrictModel):
    items: list[EditDocumentListItem]
    next_cursor: str | None


def document_label(document_json: dict[str, Any]) -> str:
    for clip in document_json.get("clips", []):
        heading = clip.get("heading") if clip.get("kind") == "text" else None
        if isinstance(heading, str) and heading.strip():
            return heading.strip()[:120]
    return "Untitled draft"
```

In `PostgresEditDocumentRepository`, add a method that follows the `editor_asset_repository.py`
keyset pattern (`_cursor_token` and `_decode_cursor` copied as module helpers, one short-lived
`AsyncConnection`):
```python
    async def list_documents(self, *, project_id: str, limit: int, cursor: str | None) -> EditDocumentListPage:
        clamped = max(1, min(int(limit), 50))
        keyset = _decode_cursor(cursor) if cursor else None
        query = f"""
            WITH latest AS (
                SELECT DISTINCT ON (document_id) document_id, revision, created_at, document_json
                FROM edit_document_revisions WHERE project_id = %s
                ORDER BY document_id, revision DESC
            )
            SELECT l.document_id, l.revision, l.created_at, l.document_json,
                   EXISTS (SELECT 1 FROM studio_import_drafts d
                           WHERE d.project_id = %s AND d.document_id = l.document_id)
            FROM latest l
            {"WHERE (l.created_at, l.document_id) < (%s, %s)" if keyset else ""}
            ORDER BY l.created_at DESC, l.document_id DESC
            LIMIT %s
        """
        params = (project_id, project_id, *(keyset or ()), clamped + 1)
        connection = await AsyncConnection.connect(self._database_url)
        async with connection:
            cursor_ = connection.cursor()
            await cursor_.execute(query, params)
            rows = await cursor_.fetchall()
        page = rows[:clamped]
        items = [
            EditDocumentListItem(document_id=d, revision=r, updated_at=c, label=document_label(j), imported=i)
            for d, r, c, j, i in page
        ]
        next_cursor = _cursor_token(page[-1][2], page[-1][0]) if len(rows) > clamped else None
        return EditDocumentListPage(items=items, next_cursor=next_cursor)
```
Wrap the database part in the same `try`/`except` this repository already uses, raising its
persistence error (the one mapped to 503 for the other reads).

`EditDocumentService.list_documents(project_id, limit, cursor)` delegates to the repository,
behind the same `_store()` guard as `get`.

Add the route in `api/routes/edit_documents.py`, **above** the
`/projects/{project_id}/edit-documents/{document_id}` route:
```python
@router.get("/projects/{project_id}/edit-documents", response_model=EditDocumentListPage)
async def list_edit_documents(
    project_id: str,
    actor: Annotated[Actor, Depends(current_actor)],
    service: Annotated[EditDocumentService, Depends(get_edit_document_service)],
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> EditDocumentListPage:
    return await service.list_documents(project_id=project_id, limit=limit, cursor=cursor)
```
Use the dependency name this file already uses for the service.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `make test T=tests/domain/test_edit_document_list.py tests/api/test_edit_documents.py tests/application/test_edit_documents.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add python/src/thoth_control_plane/domain/edit_document_list.py python/src/thoth_control_plane/application python/src/thoth_control_plane/infrastructure/editor_repository.py python/src/thoth_control_plane/api/routes/edit_documents.py python/tests/domain/test_edit_document_list.py python/tests/api/test_edit_documents.py
git commit -m "feat(studio): list a project's Studio documents"
```

### Task 9: The voice adapter

**Files:**
- Create: `python/src/thoth_control_plane/voice/__init__.py`, `voice/ports.py`, `voice/audio.py`, `voice/adapters/__init__.py`, `voice/adapters/elevenlabs.py`, `voice/adapters/openai_compatible.py`, `voice/factory.py`
- Modify: `python/src/thoth_control_plane/config.py`
- Modify: `python/src/thoth_control_plane/cli.py` (`voice say`)
- Test: `python/tests/voice/__init__.py`, `python/tests/voice/test_elevenlabs.py`, `python/tests/voice/test_openai_compatible.py`, `python/tests/voice/test_factory_and_cli.py`

**Interfaces:**
- Produces:
  - `VoiceRequest`, `WordTiming` and `SynthesizedVoice`;
  - `VoiceSynthesizer` (Protocol);
  - `VoiceUnavailable`, `VoiceRejected` (`.code`) and `VoiceNotConfigured`;
  - `ElevenLabsVoice(api_key, *, transport=None)`;
  - `OpenAICompatibleVoice(base_url, api_key, *, http_client=None)`;
  - `build_voice(settings, provider)`;
  - `words_from_alignment(alignment)`;
  - `probe_duration(audio: bytes) -> float`.

- [ ] **Step 1: Write the failing tests**

`python/tests/voice/test_elevenlabs.py`:
```python
import base64
import json

import httpx
import pytest

from thoth_control_plane.voice.adapters.elevenlabs import ElevenLabsVoice, words_from_alignment
from thoth_control_plane.voice.ports import VoiceRejected, VoiceRequest, VoiceUnavailable

ALIGNMENT = {
    "characters": list("Halo,  dunia!"),
    "character_start_times_seconds": [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.55, 0.6, 0.7, 0.8, 0.9, 1.0, 1.1],
    "character_end_times_seconds": [0.1, 0.2, 0.3, 0.4, 0.5, 0.55, 0.6, 0.7, 0.8, 0.9, 1.0, 1.1, 1.2],
}


def test_alignment_groups_runs_of_non_space_characters_into_words() -> None:
    words = words_from_alignment(ALIGNMENT)
    assert [(w.text, w.start_seconds, w.end_seconds) for w in words] == [("Halo,", 0.0, 0.5), ("dunia!", 0.6, 1.2)]


@pytest.mark.asyncio
async def test_synthesize_posts_with_timestamps_and_decodes_audio() -> None:
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"], seen["key"], seen["body"] = str(request.url), request.headers["xi-api-key"], json.loads(request.content)
        return httpx.Response(200, json={"audio_base64": base64.b64encode(b"MP3").decode(), "alignment": ALIGNMENT})

    voice = await ElevenLabsVoice("secret-key", transport=httpx.MockTransport(handler)).synthesize(
        VoiceRequest(text="Halo, dunia!", voice_id="plgKUYgnlZ1DCNh54DwJ")
    )
    assert voice.audio == b"MP3" and voice.media_type == "audio/mpeg" and voice.duration_seconds == 1.2
    assert "/v1/text-to-speech/plgKUYgnlZ1DCNh54DwJ/with-timestamps" in seen["url"]
    assert "output_format=mp3_44100_128" in seen["url"] and seen["key"] == "secret-key"
    assert seen["body"]["model_id"] == "eleven_multilingual_v2" and "language_code" not in seen["body"]


@pytest.mark.asyncio
@pytest.mark.parametrize(("status", "error"), [(401, VoiceRejected), (422, VoiceRejected), (429, VoiceUnavailable), (503, VoiceUnavailable)])
async def test_errors_map_and_never_carry_the_key(status, error) -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(status, json={"detail": {"status": "x"}}))
    with pytest.raises(error) as caught:
        await ElevenLabsVoice("secret-key", transport=transport).synthesize(VoiceRequest(text="a", voice_id="v"))
    assert "secret-key" not in str(caught.value) and "secret-key" not in repr(caught.value)
```

`python/tests/voice/test_openai_compatible.py`:
```python
import io
import json
import wave

import httpx
import pytest

from thoth_control_plane.voice.adapters.openai_compatible import OpenAICompatibleVoice
from thoth_control_plane.voice.ports import VoiceRejected, VoiceRequest, VoiceUnavailable


def wav(seconds: float) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(8000)
        handle.writeframes(b"\0\0" * int(8000 * seconds))
    return buffer.getvalue()


@pytest.mark.asyncio
async def test_speech_request_carries_model_voice_speed_and_language() -> None:
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"], seen["body"] = request.url.path, json.loads(request.content)
        return httpx.Response(200, content=wav(1.5), headers={"content-type": "audio/wav"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    voice = await OpenAICompatibleVoice("http://voices.test/v1", None, http_client=client).synthesize(
        VoiceRequest(text="Halo", voice_id="M1", model="supertonic3", speed=1.1)
    )
    assert seen["path"] == "/v1/audio/speech"
    assert seen["body"] == {"model": "supertonic3", "voice": "M1", "input": "Halo", "response_format": "wav", "speed": 1.1, "language": "id"}
    assert voice.media_type == "audio/wav" and voice.word_timings is None
    assert abs(voice.duration_seconds - 1.5) < 0.01


@pytest.mark.asyncio
async def test_a_model_is_required_and_errors_map() -> None:
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(500)))
    adapter = OpenAICompatibleVoice("http://voices.test/v1", None, http_client=client)
    with pytest.raises(VoiceRejected):
        await adapter.synthesize(VoiceRequest(text="a", voice_id="v"))
    with pytest.raises(VoiceUnavailable):
        await adapter.synthesize(VoiceRequest(text="a", voice_id="v", model="m"))
```

`python/tests/voice/test_factory_and_cli.py`:
```python
import json

import pytest
from typer.testing import CliRunner

from thoth_control_plane import cli
from thoth_control_plane.config import Settings
from thoth_control_plane.voice.factory import build_voice
from thoth_control_plane.voice.ports import SynthesizedVoice, VoiceNotConfigured, WordTiming


@pytest.mark.parametrize("provider", ["elevenlabs", "openai_compatible"])
def test_unconfigured_providers_refuse(provider) -> None:
    with pytest.raises(VoiceNotConfigured):
        build_voice(Settings(THOTH_CONTROL_PLANE_API_KEY="k"), provider)


def test_voice_say_writes_audio_and_words(monkeypatch, tmp_path) -> None:
    class Fake:
        async def synthesize(self, request):
            return SynthesizedVoice(audio=b"MP3", media_type="audio/mpeg", duration_seconds=1.0,
                                    word_timings=[WordTiming(text="Halo", start_seconds=0.0, end_seconds=0.4)])

    monkeypatch.setenv("THOTH_CONTROL_PLANE_API_KEY", "k")
    monkeypatch.setattr(cli, "build_voice", lambda settings, provider: Fake())
    out = tmp_path / "say.mp3"
    result = CliRunner().invoke(cli.app, ["voice", "say", "--voice", "v", "--text", "Halo", "--out", str(out)])
    assert result.exit_code == 0 and result.output.strip() == "provider=elevenlabs duration_seconds=1.00 words=1"
    assert out.read_bytes() == b"MP3"
    assert json.loads((tmp_path / "say.mp3.words.json").read_text()) == [{"text": "Halo", "start_seconds": 0.0, "end_seconds": 0.4}]


def test_voice_say_reports_an_unconfigured_provider(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("THOTH_CONTROL_PLANE_API_KEY", "k")
    result = CliRunner().invoke(cli.app, ["voice", "say", "--provider", "openai-compatible", "--voice", "v", "--text", "a", "--out", str(tmp_path / "x.wav")])
    assert result.exit_code == 1 and "VoiceNotConfigured" in result.output
```

- [ ] **Step 2: Run them to verify they fail**

Run: `make test T=tests/voice`
Expected: FAIL with `No module named thoth_control_plane.voice`.

- [ ] **Step 3: Implement**

`voice/ports.py`:
```python
"""The voice port (spec 2026-10-18, section 9). Two providers; edge-tts is excluded."""

from __future__ import annotations

from typing import Annotated, Literal, Protocol

from pydantic import Field

from thoth_control_plane.domain.models import StrictModel


class VoiceRequest(StrictModel):
    text: Annotated[str, Field(min_length=1, max_length=5000)]
    language: Annotated[str, Field(min_length=2, max_length=8)] = "id"
    voice_id: Annotated[str, Field(min_length=1, max_length=200)]
    model: Annotated[str, Field(min_length=1, max_length=200)] | None = None
    speed: Annotated[float, Field(ge=0.7, le=1.5)] = 1.0


class WordTiming(StrictModel):
    text: str
    start_seconds: float
    end_seconds: float


class SynthesizedVoice(StrictModel):
    audio: bytes
    media_type: Literal["audio/mpeg", "audio/wav"]
    duration_seconds: float
    word_timings: list[WordTiming] | None


class VoiceSynthesizer(Protocol):
    async def synthesize(self, request: VoiceRequest) -> SynthesizedVoice: ...


class VoiceUnavailable(RuntimeError):
    """Timeout, connection failure, 429 or 5xx: retryable."""


class VoiceRejected(ValueError):
    """Any other 4xx: not retryable. Carries the provider's code, never a credential."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class VoiceNotConfigured(RuntimeError):
    """The provider has no credentials or base URL."""
```

`voice/audio.py`:
```python
"""Audio duration by PyAV (already installed)."""

import io

import av


def probe_duration(audio: bytes) -> float:
    with av.open(io.BytesIO(audio)) as container:
        if container.duration:
            return container.duration / av.time_base
        stream = container.streams.audio[0]
        return float(stream.duration * stream.time_base)
```

`voice/adapters/elevenlabs.py`:
```python
"""ElevenLabs text-to-speech with character timestamps (the primary provider)."""

from __future__ import annotations

import base64
from typing import Any
from urllib.parse import quote

import httpx

from thoth_control_plane.voice.audio import probe_duration
from thoth_control_plane.voice.ports import (
    SynthesizedVoice,
    VoiceRejected,
    VoiceRequest,
    VoiceUnavailable,
    WordTiming,
)

DEFAULT_MODEL = "eleven_multilingual_v2"
BASE_URL = "https://api.elevenlabs.io"


def words_from_alignment(alignment: dict[str, Any]) -> list[WordTiming]:
    words: list[WordTiming] = []
    text, start, end = "", 0.0, 0.0
    for char, char_start, char_end in zip(
        alignment["characters"],
        alignment["character_start_times_seconds"],
        alignment["character_end_times_seconds"],
        strict=True,
    ):
        if char.isspace():
            if text:
                words.append(WordTiming(text=text, start_seconds=start, end_seconds=end))
                text = ""
            continue
        if not text:
            start = char_start
        text, end = text + char, char_end
    if text:
        words.append(WordTiming(text=text, start_seconds=start, end_seconds=end))
    return words


def raise_for_status(response: httpx.Response, provider: str) -> None:
    if response.status_code < 400:
        return
    code = f"{provider}_http_{response.status_code}"
    if response.status_code == 429 or response.status_code >= 500:
        raise VoiceUnavailable(code)
    raise VoiceRejected(code)


class ElevenLabsVoice:
    def __init__(self, api_key: str, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._key = api_key
        self._transport = transport

    def __repr__(self) -> str:
        return "ElevenLabsVoice()"

    async def synthesize(self, request: VoiceRequest) -> SynthesizedVoice:
        body = {
            "text": request.text,
            "model_id": request.model or DEFAULT_MODEL,
            "voice_settings": {"speed": request.speed},
        }
        try:
            async with httpx.AsyncClient(base_url=BASE_URL, transport=self._transport, timeout=120) as http:
                response = await http.post(
                    f"/v1/text-to-speech/{quote(request.voice_id, safe='')}/with-timestamps",
                    params={"output_format": "mp3_44100_128"},
                    headers={"xi-api-key": self._key},
                    json=body,
                )
        except httpx.HTTPError:
            raise VoiceUnavailable("elevenlabs_unreachable") from None
        raise_for_status(response, "elevenlabs")
        payload = response.json()
        audio = base64.b64decode(payload["audio_base64"])
        alignment = payload.get("alignment")
        words = words_from_alignment(alignment) if alignment else None
        duration = words[-1].end_seconds if words else probe_duration(audio)
        return SynthesizedVoice(audio=audio, media_type="audio/mpeg", duration_seconds=duration, word_timings=words)
```

`voice/adapters/openai_compatible.py`:
```python
"""Any OpenAI-compatible speech server: VoiceStudio, OpenAI, or another self-hosted one."""

from __future__ import annotations

import httpx
import openai

from thoth_control_plane.voice.audio import probe_duration
from thoth_control_plane.voice.ports import SynthesizedVoice, VoiceRejected, VoiceRequest, VoiceUnavailable


class OpenAICompatibleVoice:
    def __init__(self, base_url: str, api_key: str | None, *, http_client: httpx.AsyncClient | None = None) -> None:
        self._client = openai.AsyncOpenAI(
            base_url=base_url, api_key=api_key or "unused", http_client=http_client, max_retries=0
        )

    async def synthesize(self, request: VoiceRequest) -> SynthesizedVoice:
        if not request.model:
            raise VoiceRejected("openai_compatible_model_required")
        try:
            response = await self._client.audio.speech.create(
                model=request.model, voice=request.voice_id, input=request.text,
                response_format="wav", speed=request.speed, extra_body={"language": request.language},
            )
        except openai.APIStatusError as error:
            code = f"openai_compatible_http_{error.status_code}"
            if error.status_code == 429 or error.status_code >= 500:
                raise VoiceUnavailable(code) from None
            raise VoiceRejected(code) from None
        except openai.APIConnectionError:
            raise VoiceUnavailable("openai_compatible_unreachable") from None
        audio = response.content
        return SynthesizedVoice(audio=audio, media_type="audio/wav", duration_seconds=probe_duration(audio), word_timings=None)
```

`voice/factory.py`:
```python
"""Build one configured provider; an unconfigured one refuses instead of falling back."""

from typing import Literal

from thoth_control_plane.config import Settings
from thoth_control_plane.voice.adapters.elevenlabs import ElevenLabsVoice
from thoth_control_plane.voice.adapters.openai_compatible import OpenAICompatibleVoice
from thoth_control_plane.voice.ports import VoiceNotConfigured, VoiceSynthesizer

Provider = Literal["elevenlabs", "openai_compatible"]


def build_voice(settings: Settings, provider: Provider) -> VoiceSynthesizer:
    if provider == "elevenlabs":
        if settings.THOTH_ELEVENLABS_API_KEY is None:
            raise VoiceNotConfigured("elevenlabs")
        return ElevenLabsVoice(settings.THOTH_ELEVENLABS_API_KEY.get_secret_value())
    if settings.THOTH_VOICE_OPENAI_COMPATIBLE_BASE_URL is None:
        raise VoiceNotConfigured("openai_compatible")
    key = settings.THOTH_VOICE_OPENAI_COMPATIBLE_API_KEY
    return OpenAICompatibleVoice(
        str(settings.THOTH_VOICE_OPENAI_COMPATIBLE_BASE_URL), key.get_secret_value() if key else None
    )
```
`voice/__init__.py` and `voice/adapters/__init__.py` each hold a one-line docstring.

In `config.py`, next to `THOTH_OPENROUTER_API_KEY`:
```python
    THOTH_ELEVENLABS_API_KEY: SecretStr | None = None
    THOTH_VOICE_OPENAI_COMPATIBLE_BASE_URL: AnyHttpUrl | None = None
    THOTH_VOICE_OPENAI_COMPATIBLE_API_KEY: SecretStr | None = None
```

In `cli.py`:
```python
voice_app = typer.Typer(no_args_is_help=True)
app.add_typer(voice_app, name="voice")


@voice_app.command("say")
def voice_say(
    voice: Annotated[str, typer.Option("--voice")],
    out: Annotated[Path, typer.Option("--out")],
    provider: Annotated[str, typer.Option("--provider")] = "elevenlabs",
    model: Annotated[str | None, typer.Option("--model")] = None,
    speed: Annotated[float, typer.Option("--speed")] = 1.0,
    language: Annotated[str, typer.Option("--language")] = "id",
    text: Annotated[str | None, typer.Option("--text")] = None,
    file: Annotated[Path | None, typer.Option("--file")] = None,
) -> None:
    """Synthesize one script with a live provider (operator only; never used by tests)."""
    if (text is None) == (file is None):
        raise typer.BadParameter("give exactly one of --text or --file")
    if provider not in ("elevenlabs", "openai-compatible"):
        raise typer.BadParameter("provider must be elevenlabs or openai-compatible")
    script = text if text is not None else file.read_text(encoding="utf-8")
    try:
        synthesizer = build_voice(Settings(), provider.replace("-", "_"))
        result = asyncio.run(synthesizer.synthesize(
            VoiceRequest(text=script, voice_id=voice, model=model, speed=speed, language=language)
        ))
    except (VoiceNotConfigured, VoiceRejected, VoiceUnavailable) as error:
        typer.echo(f"{type(error).__name__}: {error}")
        raise typer.Exit(1) from None
    out.write_bytes(result.audio)
    words = [w.model_dump() for w in result.word_timings or []]
    Path(f"{out}.words.json").write_text(json.dumps(words), encoding="utf-8")
    typer.echo(f"provider={provider} duration_seconds={result.duration_seconds:.2f} words={len(words)}")
```
Import `build_voice` from `voice.factory` at module level (the test monkeypatches
`cli.build_voice`), along with `VoiceNotConfigured`, `VoiceRejected`, `VoiceRequest` and
`VoiceUnavailable` from `voice.ports`. Add `asyncio` if `cli.py` lacks it.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `make test T=tests/voice tests/test_config.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add python/src/thoth_control_plane/voice python/src/thoth_control_plane/config.py python/src/thoth_control_plane/cli.py python/tests/voice
git commit -m "feat(voice): ElevenLabs and OpenAI-compatible voice adapters with a CLI"
```

### Task 10: The contract and the dashboard client

**Files:**
- Modify: `python/openapi.json` (regenerated)
- Modify: `dashboard/src/api/generated/control-plane.ts` (regenerated)
- Modify: `dashboard/src/api/control-plane.ts`
- Test: `dashboard/src/api/control-plane.test.ts` (append)

**Interfaces:**
- Produces, in `control-plane.ts`:
  - the types `Project`, `WorkflowRun`, `WorkflowRunPage`, `EditDocumentListItem` and
    `EditDocumentListPage`;
  - the client methods:
    - `listProjects(): Promise<Project[]>`;
    - `createProject(name): Promise<Project>`;
    - `startProjectWorkflow(projectId, request, key): Promise<WorkflowSummary>`;
    - `listProjectWorkflows(projectId, cursor?): Promise<WorkflowRunPage>`;
    - `listUnassignedWorkflows(cursor?): Promise<WorkflowRunPage>`;
    - `moveWorkflow(workflowId, projectId): Promise<WorkflowRun>`;
    - `downloadWorkflowArtifact(workflowId, artifactId): Promise<Blob>`;
    - `listEditDocuments(projectId, cursor?): Promise<EditDocumentListPage>`.
  - `streamWorkflow` stops after a terminal or history-expired snapshot (ruling P6).

- [ ] **Step 1: Regenerate the contract**

Run: `uv run --project python python python/scripts/export_openapi.py && cd dashboard && bun run generate:control-plane-types`
Expected: `git diff --stat` shows `python/openapi.json` and `dashboard/src/api/generated/control-plane.ts` changed.
`grep -c '"/api/v1/projects/{project_id}/workflows"' python/openapi.json` prints 1.

- [ ] **Step 2: Write the failing client tests**

Append to `dashboard/src/api/control-plane.test.ts`:
```ts
test("project and workflow-run calls hit the new routes", async () => {
  const calls: string[] = [];
  const fetchStub = (async (input: RequestInfo | URL, init?: RequestInit) => {
    calls.push(`${init?.method ?? "GET"} ${String(input)}`);
    if (String(input).endsWith("/artifacts/clip")) return new Response("BYTES");
    return new Response(JSON.stringify({ items: [], next_cursor: null, project_id: "p1", name: "N" }), { headers: { "Content-Type": "application/json" } });
  }) as typeof fetch;
  const client = createControlPlaneClient({ baseUrl: "", apiKey: "k", fetch: fetchStub });
  await client.listProjects();
  await client.createProject("N");
  await client.listProjectWorkflows("p1", "c1");
  await client.listUnassignedWorkflows();
  await client.moveWorkflow("wf_1", "p1");
  await client.listEditDocuments("p1");
  expect(await (await client.downloadWorkflowArtifact("wf_1", "clip")).text()).toBe("BYTES");
  expect(calls).toEqual([
    "GET /api/v1/projects",
    "POST /api/v1/projects",
    "GET /api/v1/projects/p1/workflows?limit=20&cursor=c1",
    "GET /api/v1/workflows?unassigned=true&limit=50",
    "PATCH /api/v1/workflows/wf_1",
    "GET /api/v1/projects/p1/edit-documents?limit=20",
    "GET /api/v1/workflows/wf_1/artifacts/clip",
  ]);
});

test("the workflow stream stops polling once a snapshot is terminal", async () => {
  let snapshots = 0;
  const fetchStub = (async (input: RequestInfo | URL) => {
    if (String(input).endsWith("/events")) return new Response(null, { status: 503 });
    snapshots += 1;
    return new Response(JSON.stringify({ workflow_id: "wf_1", status: "succeeded", stages: [], artifacts: [], source: { display_url: "https://x.test", platform: "x" }, created_at: "", updated_at: "" }), { headers: { "Content-Type": "application/json" } });
  }) as typeof fetch;
  const stop = createControlPlaneClient({ baseUrl: "", apiKey: "k", fetch: fetchStub }).streamWorkflow("wf_1", () => {});
  await new Promise((resolve) => setTimeout(resolve, 2_500));
  stop();
  expect(snapshots).toBeLessThanOrEqual(2);
});
```
The existing `streamWorkflow` uses the global `fetch` for the events request. Step 4 routes it
through `doFetch`, so the stub sees it.

- [ ] **Step 3: Run them to verify they fail**

Run: `cd dashboard && bun test src/api/control-plane.test.ts`
Expected: FAIL with `client.listProjects is not a function`.

- [ ] **Step 4: Implement**

In `control-plane.ts`, add the type aliases next to `WorkflowSummary`:
```ts
export type Project = components["schemas"]["Project"];
export type WorkflowRun = components["schemas"]["WorkflowRun"];
export type WorkflowRunPage = components["schemas"]["WorkflowRunPage"];
export type EditDocumentListItem = components["schemas"]["EditDocumentListItem"];
export type EditDocumentListPage = components["schemas"]["EditDocumentListPage"];
```
Add the eight signatures from **Interfaces** to `ControlPlaneClient`, and to the `client` object:
```ts
    listProjects: async () => (await request<{ items: Project[] }>("/api/v1/projects")).items,
    createProject: (name) =>
      request<Project>("/api/v1/projects", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name }),
      }),
    startProjectWorkflow: (projectId, workflow, idempotencyKey) =>
      request<WorkflowSummary>(`/api/v1/projects/${encodeURIComponent(projectId)}/workflows`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "Idempotency-Key": idempotencyKey },
        body: JSON.stringify(workflow),
      }),
    listProjectWorkflows: (projectId, cursor) => {
      const query = new URLSearchParams({ limit: "20" });
      if (cursor) query.set("cursor", cursor);
      return request<WorkflowRunPage>(`/api/v1/projects/${encodeURIComponent(projectId)}/workflows?${query}`);
    },
    listUnassignedWorkflows: (cursor) => {
      const query = new URLSearchParams({ unassigned: "true", limit: "50" });
      if (cursor) query.set("cursor", cursor);
      return request<WorkflowRunPage>(`/api/v1/workflows?${query}`);
    },
    moveWorkflow: (workflowId, projectId) =>
      request<WorkflowRun>(`/api/v1/workflows/${encodeURIComponent(workflowId)}`, {
        method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ project_id: projectId }),
      }),
    downloadWorkflowArtifact: async (workflowId, artifactId) => {
      const response = await doFetch(
        `${baseUrl}/api/v1/workflows/${encodeURIComponent(workflowId)}/artifacts/${encodeURIComponent(artifactId)}`,
        { headers: headers() },
      );
      if (!response.ok) throw new Error(`Control plane request failed (${response.status})`);
      return response.blob();
    },
    listEditDocuments: (projectId, cursor) => {
      const query = new URLSearchParams({ limit: "20" });
      if (cursor) query.set("cursor", cursor);
      return request<EditDocumentListPage>(`/api/v1/projects/${encodeURIComponent(projectId)}/edit-documents?${query}`);
    },
```
In `streamWorkflow`, apply ruling P6:
- add `let finished = false;`;
- inside `refreshSnapshot`, after `onSnapshot(snapshot)` (assign the awaited value to `snapshot`
  first), add
  `if (["succeeded", "failed", "cancelled"].includes(snapshot.status) || snapshot.history_expired) finished = true;`;
- change both `while (active)` loop guards to `while (active && !finished)`;
- replace the events `fetch(` with `doFetch(`.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd dashboard && bun test src/api/control-plane.test.ts`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add python/openapi.json dashboard/src/api/generated/control-plane.ts dashboard/src/api/control-plane.ts dashboard/src/api/control-plane.test.ts
git commit -m "feat(dashboard): client calls for projects, runs, and Studio documents"
```

### Task 11: Workflows pages, monitor downloads, and the wizard copy

**Files:**
- Create: `dashboard/src/features/workflows/WorkflowsPage.tsx`
- Create: `dashboard/src/features/workflows/WorkflowDetailPage.tsx`
- Modify: `dashboard/src/components/WorkflowMonitor.tsx` (download buttons; the history-expired notice)
- Modify: `dashboard/src/components/WorkflowWizard.tsx` (copy; remove the disabled option)
- Test: `dashboard/src/features/workflows/WorkflowsPage.test.tsx`, `dashboard/src/components/WorkflowMonitor.test.tsx` (create or append)

**Interfaces:**
- Consumes: the client methods from Task 10.
- Produces:
  - `WorkflowsPage({ client, projectId, projects, onRuns? })`;
  - `WorkflowDetailPage({ client, workflowId })`.

- [ ] **Step 1: Write the failing tests**

`dashboard/src/features/workflows/WorkflowsPage.test.tsx`:
```tsx
/// <reference types="bun-types" />
import { afterEach, expect, mock, test } from "bun:test";
import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router";
import { WorkflowsPage } from "./WorkflowsPage";

afterEach(cleanup);
const run = (id: string, extra = {}) => ({ workflow_id: id, project_id: "p1", source: { display_url: `https://x.test/${id}`, platform: "x" }, status: "succeeded", history_expired: false, artifact_count: 2, created_at: "2026-10-18", updated_at: "2026-10-18", ...extra });

function client(overrides = {}) {
  return {
    listStylePresets: mock(async () => [{ preset_id: "news", label: "News", description: "" }]),
    startProjectWorkflow: mock(async () => ({ workflow_id: "wf_new" })),
    listProjectWorkflows: mock(async (_p: string, cursor?: string) => cursor ? { items: [run("wf_b")], next_cursor: null } : { items: [run("wf_a")], next_cursor: "c1" }),
    listUnassignedWorkflows: mock(async () => ({ items: [run("wf_old", { project_id: null, status: "unknown", history_expired: true })], next_cursor: null })),
    moveWorkflow: mock(async () => run("wf_old")),
    ...overrides,
  } as never;
}

test("without a project the start button is disabled and says why", async () => {
  render(<MemoryRouter><WorkflowsPage client={client()} projectId={null} projects={[]} /></MemoryRouter>);
  expect((await screen.findByRole("button", { name: /Start pipeline/ }) as HTMLButtonElement).disabled).toBe(true);
  expect(screen.getAllByText("Select or create a project to start a workflow.").length).toBeGreaterThan(0);
});

test("lists the project's runs, loads more, and moves an unassigned run", async () => {
  const c = client();
  render(<MemoryRouter><WorkflowsPage client={c} projectId="p1" projects={[{ project_id: "p1", name: "News", created_at: "", updated_at: "" }]} /></MemoryRouter>);
  expect(await screen.findByRole("button", { name: "https://x.test/wf_a" })).toBeDefined();
  await userEvent.setup().click(screen.getByRole("button", { name: "Load more" }));
  expect(await screen.findByRole("button", { name: "https://x.test/wf_b" })).toBeDefined();
  const unassigned = screen.getByText(/Unassigned/).closest("details")!;
  expect(within(unassigned).getByText(/history expired/)).toBeDefined();
  await userEvent.setup().selectOptions(within(unassigned).getByRole("combobox"), "p1");
  expect((c as { moveWorkflow: ReturnType<typeof mock> }).moveWorkflow).toHaveBeenCalledWith("wf_old", "p1");
});

test("a started workflow opens its detail route", async () => {
  render(
    <MemoryRouter initialEntries={["/workflows"]}>
      <Routes>
        <Route path="/workflows" element={<WorkflowsPage client={client()} projectId="p1" projects={[]} />} />
        <Route path="/workflows/:id" element={<p>detail page</p>} />
      </Routes>
    </MemoryRouter>,
  );
  const user = userEvent.setup();
  await user.type(await screen.findByLabelText("Source URL"), "https://www.tiktok.com/@a/video/1");
  await screen.findByRole("option", { name: "News" });
  await user.click(screen.getByRole("button", { name: /Start pipeline/ }));
  expect(await screen.findByText("detail page")).toBeDefined();
  expect(screen.queryByText("From source to finished cut")).toBeNull();
});
```

Add to `dashboard/src/components/WorkflowMonitor.test.tsx` (create it if missing, with the same
imports):
```tsx
test("results download through the client and an expired history is announced", async () => {
  const blob = new Blob(["{}"]);
  const client = {
    streamWorkflow: (_id: string, onSnapshot: (s: unknown) => void) => { onSnapshot({ workflow_id: "wf_1", status: "succeeded", stages: [], source: { display_url: "https://x.test", platform: "x" }, artifacts: [{ artifact_id: "content_set", kind: "content_set", label: "Content set", media_type: "application/json", location: "reports/wf_1/content-set.json" }], history_expired: true, created_at: "", updated_at: "" }); return () => {}; },
    downloadWorkflowArtifact: mock(async () => blob),
    cancelWorkflow: mock(), retryWorkflow: mock(), approveWorkflow: mock(),
  } as never;
  globalThis.URL.createObjectURL = () => "blob:x";
  globalThis.URL.revokeObjectURL = () => {};
  render(<WorkflowMonitor workflowId="wf_1" client={client} />);
  expect(await screen.findByText("History expired; showing the stored result.")).toBeDefined();
  await userEvent.setup().click(screen.getByRole("button", { name: "Content set" }));
  expect((client as { downloadWorkflowArtifact: ReturnType<typeof mock> }).downloadWorkflowArtifact).toHaveBeenCalledWith("wf_1", "content_set");
});
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd dashboard && bun add react-router@^7 && bun test src/features/workflows src/components/WorkflowMonitor.test.tsx`
Expected: FAIL. `./WorkflowsPage` cannot be resolved, and the monitor test cannot find the
download button.

- [ ] **Step 3: Implement**

`dashboard/src/features/workflows/WorkflowsPage.tsx`:
```tsx
import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router";
import type { ControlPlaneClient, Project, WorkflowRequest, WorkflowRun } from "@/api/control-plane";
import { Button } from "@/components/ui/button";
import { WorkflowWizard } from "@/components/WorkflowWizard";

type WorkflowsClient = Pick<ControlPlaneClient, "listStylePresets" | "startProjectWorkflow" | "listProjectWorkflows" | "listUnassignedWorkflows" | "moveWorkflow">;
const NO_PROJECT = "Select or create a project to start a workflow.";
const runStatus = (run: WorkflowRun) => (run.history_expired ? `${run.status} · history expired` : run.status);

export function WorkflowsPage({ client, projectId, projects, onRuns }: { client: WorkflowsClient; projectId: string | null; projects: Project[]; onRuns?: (runs: WorkflowRun[]) => void }) {
  const navigate = useNavigate();
  const [runs, setRuns] = useState<WorkflowRun[]>([]);
  const [next, setNext] = useState<string | null>(null);
  const [loose, setLoose] = useState<WorkflowRun[]>([]);
  const [looseNext, setLooseNext] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [reload, setReload] = useState(0);

  useEffect(() => {
    setError("");
    if (!projectId) { setRuns([]); setNext(null); onRuns?.([]); return; }
    let live = true;
    client.listProjectWorkflows(projectId).then(
      (page) => { if (!live) return; setRuns(page.items); setNext(page.next_cursor ?? null); onRuns?.(page.items); },
      () => { if (live) setError("Runs could not be loaded. Try again."); },
    );
    return () => { live = false; };
  }, [client, projectId, reload, onRuns]);

  useEffect(() => {
    let live = true;
    client.listUnassignedWorkflows().then((page) => { if (!live) return; setLoose(page.items); setLooseNext(page.next_cursor ?? null); }, () => {});
    return () => { live = false; };
  }, [client, reload]);

  const wizardClient = useMemo(() => ({
    listStylePresets: () => client.listStylePresets(),
    createWorkflow: (request: WorkflowRequest, key: string) => client.startProjectWorkflow(projectId ?? "", request, key),
  }), [client, projectId]);

  const more = async () => {
    if (!projectId || !next) return;
    const page = await client.listProjectWorkflows(projectId, next);
    setRuns((current) => [...current, ...page.items]);
    setNext(page.next_cursor ?? null);
  };
  const moreLoose = async () => {
    if (!looseNext) return;
    const page = await client.listUnassignedWorkflows(looseNext);
    setLoose((current) => [...current, ...page.items]);
    setLooseNext(page.next_cursor ?? null);
  };
  const move = async (workflowId: string, target: string) => {
    try { await client.moveWorkflow(workflowId, target); setReload((n) => n + 1); }
    catch { setError("The run could not be moved. Try again."); }
  };
  const open = (run: WorkflowRun) => navigate(`/workflows/${encodeURIComponent(run.workflow_id)}`);

  return (
    <div className="dashboard-workflows">
      <WorkflowWizard client={wizardClient} onStarted={(id) => navigate(`/workflows/${encodeURIComponent(id)}`)} disabledReason={projectId ? undefined : NO_PROJECT} />
      <section className="pen-recent-runs">
        <header><h2>Runs in this project</h2></header>
        <div className="pen-runs-table">
          <table>
            <thead><tr>{["Source", "Status", "Last update", "Output"].map((heading) => <th key={heading}>{heading}</th>)}</tr></thead>
            <tbody>{runs.map((run) => (
              <tr key={run.workflow_id}>
                <td><button type="button" className="pen-run-link" onClick={() => open(run)}>{run.source.display_url}</button></td>
                <td>{runStatus(run)}</td><td>{run.updated_at}</td>
                <td>{run.artifact_count ? `${run.artifact_count} artifacts` : "—"}</td>
              </tr>
            ))}</tbody>
          </table>
          {!runs.length && <p className="pen-empty-runs">{projectId ? "No runs in this project yet." : NO_PROJECT}</p>}
          {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
          {next && <Button variant="outline" onClick={() => void more()}>Load more</Button>}
        </div>
      </section>
      {loose.length > 0 && (
        <details className="pen-workflow-details">
          <summary>{`Unassigned (${loose.length}${looseNext ? "+" : ""})`}</summary>
          <ul>{loose.map((run) => (
            <li key={run.workflow_id}>
              <button type="button" className="pen-run-link" onClick={() => open(run)}>{run.source.display_url}</button>
              <span>{runStatus(run)}</span>
              <select aria-label={`Move ${run.source.display_url} to project`} defaultValue="" onChange={(event) => event.target.value && void move(run.workflow_id, event.target.value)}>
                <option value="">Move to project…</option>
                {projects.map((project) => <option key={project.project_id} value={project.project_id}>{project.name}</option>)}
              </select>
            </li>
          ))}</ul>
          {looseNext && <Button variant="outline" onClick={() => void moreLoose()}>Load more unassigned</Button>}
        </details>
      )}
    </div>
  );
}
```

`dashboard/src/features/workflows/WorkflowDetailPage.tsx`:
```tsx
import type { ControlPlaneClient } from "@/api/control-plane";
import { WorkflowMonitor } from "@/components/WorkflowMonitor";

export function WorkflowDetailPage({ client, workflowId }: { client: Pick<ControlPlaneClient, "streamWorkflow" | "cancelWorkflow" | "retryWorkflow" | "approveWorkflow" | "downloadWorkflowArtifact">; workflowId: string }) {
  return <div className="dashboard-workflows"><WorkflowMonitor workflowId={workflowId} client={client} /></div>;
}
```

In `WorkflowMonitor.tsx`:
- add `"downloadWorkflowArtifact"` to the `MonitorClient` `Pick`;
- add `ArtifactRef` to the type import;
- inside the component, add:
  ```tsx
  const download = async (artifact: ArtifactRef) => {
    try {
      const url = URL.createObjectURL(await client.downloadWorkflowArtifact(workflowId!, artifact.artifact_id));
      const link = document.createElement("a");
      link.href = url;
      link.download = artifact.artifact_id;
      link.click();
      URL.revokeObjectURL(url);
    } catch {
      setActionError("The file could not be downloaded. Try again.");
    }
  };
  ```
- replace the Results card's `<li ...>{artifact.label}</li>` with
  `<li key={artifact.artifact_id}><Button size="sm" variant="ghost" onClick={() => void download(artifact)}>{artifact.label}</Button></li>`;
- right before the Results card, add
  `{workflow?.history_expired && <p role="status" className="text-sm text-muted-foreground">History expired; showing the stored result.</p>}`.

In `WorkflowWizard.tsx`:
- the title `From source to finished cut` becomes `From source to content set`;
- the option `Approval before publishing` becomes `Approval before the content set is final`;
- delete the `<option value="stages" disabled>…</option>` line.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd dashboard && bun test src/features/workflows src/components`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add dashboard/package.json dashboard/bun.lock dashboard/src/features/workflows dashboard/src/components/WorkflowMonitor.tsx dashboard/src/components/WorkflowMonitor.test.tsx dashboard/src/components/WorkflowWizard.tsx
git commit -m "feat(dashboard): workflow list and detail pages with downloads"
```

### Task 12: The Studio document list and the resolve-only import gate

**Files:**
- Create: `dashboard/src/features/studio/StudioDocumentsPage.tsx`
- Create: `dashboard/src/lib/document-label.ts`
- Modify: `dashboard/src/features/studio/StudioImportGate.tsx` (optional `source`, resolve-only mode)
- Modify: `dashboard/src/features/studio/GuidedStudio.tsx` (remove the disabled rename button)
- Modify: `dashboard/src/features/studio/RenderPanel.tsx` (hide the Format row without a preset)
- Test: `dashboard/src/features/studio/StudioDocumentsPage.test.tsx`, `dashboard/src/features/studio/StudioImportGate.test.tsx` (append), `dashboard/src/lib/document-label.test.ts`

**Interfaces:**
- Produces:
  - `StudioDocumentsPage({ client, projectId })`;
  - `documentLabel(document: EditDocument): string`;
  - `StudioImportGate`, whose `source?: StudioSourceProjection` is optional when
    `resumeDocumentId` is set.

- [ ] **Step 1: Write the failing tests**

`dashboard/src/lib/document-label.test.ts`:
```ts
/// <reference types="bun-types" />
import { expect, test } from "bun:test";
import { documentLabel } from "./document-label";

test("the label is the first non-empty text heading", () => {
  const doc = { clips: [{ kind: "video" }, { kind: "text", heading: " " }, { kind: "text", heading: " Kucing " }] } as never;
  expect(documentLabel(doc)).toBe("Kucing");
  expect(documentLabel({ clips: [] } as never)).toBe("Untitled draft");
});
```

`dashboard/src/features/studio/StudioDocumentsPage.test.tsx`:
```tsx
/// <reference types="bun-types" />
import { afterEach, expect, mock, test } from "bun:test";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router";
import { StudioDocumentsPage } from "./StudioDocumentsPage";

afterEach(cleanup);

test("lists drafts and opens one by URL", async () => {
  const client = { listEditDocuments: mock(async () => ({ items: [{ document_id: "doc_1", revision: 3, updated_at: "2026-10-18", label: "Kucing", imported: true }], next_cursor: null })) };
  render(
    <MemoryRouter initialEntries={["/studio"]}>
      <Routes>
        <Route path="/studio" element={<StudioDocumentsPage client={client} projectId="p1" />} />
        <Route path="/studio/:projectId/:documentId" element={<p>studio for doc_1</p>} />
      </Routes>
    </MemoryRouter>,
  );
  await userEvent.setup().click(await screen.findByRole("button", { name: /Kucing/ }));
  expect(await screen.findByText("studio for doc_1")).toBeDefined();
});

test("an empty project says how to start a draft", async () => {
  const client = { listEditDocuments: mock(async () => ({ items: [], next_cursor: null })) };
  render(<MemoryRouter><StudioDocumentsPage client={client} projectId="p1" /></MemoryRouter>);
  expect(await screen.findByText("No Studio drafts in this project yet. Open a Content Set in Studio to start one.")).toBeDefined();
});
```

Append to `StudioImportGate.test.tsx`, reusing that file's existing client stub helper and
inventory fixture:
```tsx
test("resolve-only mode needs no source and never inspects", async () => {
  const client = makeClient(); // the file's existing stub factory
  render(<StudioImportGate client={client} projectId="project_001" resumeDocumentId="document_001" onOpen={() => {}} onClose={() => {}} />);
  expect(await screen.findByRole("dialog", { name: "Resolve source items" })).toBeDefined();
  expect(client.inspectStudioImport).not.toHaveBeenCalled();
});
```
If the file names its stub factory differently, use that name.

- [ ] **Step 2: Run them to verify they fail**

Run: `cd dashboard && bun test src/lib src/features/studio/StudioDocumentsPage.test.tsx src/features/studio/StudioImportGate.test.tsx`
Expected: FAIL. The modules cannot be resolved, and the gate dialog is named "Open in Studio".

- [ ] **Step 3: Implement**

`dashboard/src/lib/document-label.ts`:
```ts
import type { EditDocument } from "@/api/control-plane";

/** The first non-empty text heading, as the server's list label (spec 3.6). */
export function documentLabel(document: EditDocument): string {
  for (const clip of document.clips) {
    if (clip.kind === "text" && "heading" in clip && clip.heading.trim()) return clip.heading.trim().slice(0, 120);
  }
  return "Untitled draft";
}
```

`dashboard/src/features/studio/StudioDocumentsPage.tsx`:
```tsx
import { useEffect, useState } from "react";
import { useNavigate } from "react-router";
import type { ControlPlaneClient, EditDocumentListItem } from "@/api/control-plane";
import { Button } from "@/components/ui/button";

export function StudioDocumentsPage({ client, projectId }: { client: Pick<ControlPlaneClient, "listEditDocuments">; projectId: string }) {
  const navigate = useNavigate();
  const [items, setItems] = useState<EditDocumentListItem[]>();
  const [next, setNext] = useState<string | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let live = true;
    setItems(undefined);
    client.listEditDocuments(projectId).then(
      (page) => { if (!live) return; setItems(page.items); setNext(page.next_cursor ?? null); },
      () => { if (live) setError("Drafts could not be loaded. Try again."); },
    );
    return () => { live = false; };
  }, [client, projectId]);

  const more = async () => {
    if (!next) return;
    const page = await client.listEditDocuments(projectId, next);
    setItems((current) => [...(current ?? []), ...page.items]);
    setNext(page.next_cursor ?? null);
  };

  return (
    <section className="pen-recent-runs">
      <header><h2>Studio drafts</h2></header>
      {items?.length === 0 && <p className="pen-empty-runs">No Studio drafts in this project yet. Open a Content Set in Studio to start one.</p>}
      <ul className="pen-managed-projects">{items?.map((item) => (
        <li key={item.document_id}>
          <button type="button" onClick={() => navigate(`/studio/${encodeURIComponent(projectId)}/${encodeURIComponent(item.document_id)}`)}>
            <span>{item.label}</span><small>{`Revision ${item.revision} · ${item.updated_at}`}</small>
          </button>
        </li>
      ))}</ul>
      {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
      {next && <Button variant="outline" onClick={() => void more()}>Load more</Button>}
    </section>
  );
}
```

In `StudioImportGate.tsx`:
- the props type gets `source?: StudioSourceProjection;`;
- the inspect `useEffect` starts with `if (!source) return;`, and `source` stays in its
  dependency list;
- `const main = source?.items[0];`;
- `const title = !source ? "Resolve source items" : main?.title ? \`Open in Studio — ${main.title}\` : "Open in Studio";`;
- `const textScenes = source ? source.items.filter(...).length : 0;`, with the existing filter
  body kept;
- `create` starts with `if (!source || !inspection) return;` and passes `source` as before.

In `GuidedStudio.tsx`, delete the line
`<button type="button" className="studio-rename" aria-label="Rename document unavailable" … disabled><Pencil size={14} /></button>`
and drop `Pencil` from the icon import if it becomes unused.

In `RenderPanel.tsx`, replace
`<div><dt>Format</dt><dd>{state.capability?.preset_id ?? "Unavailable"}</dd></div>` with
`{state.capability?.preset_id ? <div><dt>Format</dt><dd>{state.capability.preset_id}</dd></div> : null}`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd dashboard && bun test src/lib src/features/studio`
Expected: PASS. Any existing assertion on "Rename document unavailable" or on "Format" with
"Unavailable" is updated to assert absence.

- [ ] **Step 5: Commit**

```bash
git add dashboard/src/lib dashboard/src/features/studio
git commit -m "feat(dashboard): Studio draft list and resolve-only import gate"
```

### Task 13: The router, the active project, and the App shell

**Files:**
- Create: `dashboard/src/lib/active-project.ts`
- Modify: `dashboard/src/App.tsx` (routing; drop the local draft, metrics and recent-runs state)
- Modify: `dashboard/src/components/ProjectSwitcher.tsx` (control-plane projects; fallback)
- Modify: `dashboard/src/components/DashboardSearch.tsx` (`Project`, `WorkflowRun`, path navigation)
- Delete: `dashboard/src/components/WorkflowDraftDialog.tsx` and its test, if any
- Modify: `dashboard/src/App.test.tsx`
- Test: `dashboard/src/lib/active-project.test.ts`

**Interfaces:**
- Consumes: `WorkflowsPage`, `WorkflowDetailPage` (Task 11); `StudioDocumentsPage`,
  `documentLabel`, the gate's resolve-only mode (Task 12); the client (Task 10).
- Produces: `useActiveProject(): [string | null, (id: string | null) => void]`.

- [ ] **Step 1: Write the failing tests**

`dashboard/src/lib/active-project.test.ts`:
```ts
/// <reference types="bun-types" />
import { afterEach, expect, test } from "bun:test";
import { act, renderHook } from "@testing-library/react";
import { useActiveProject } from "./active-project";

afterEach(() => localStorage.clear());

test("the active project persists across mounts", () => {
  const first = renderHook(() => useActiveProject());
  act(() => first.result.current[1]("p1"));
  expect(renderHook(() => useActiveProject()).result.current[0]).toBe("p1");
});

test("a storage that throws still works in memory", () => {
  const original = Storage.prototype.setItem;
  Storage.prototype.setItem = () => { throw new Error("blocked"); };
  const hook = renderHook(() => useActiveProject());
  act(() => hook.result.current[1]("p2"));
  expect(hook.result.current[0]).toBe("p2");
  Storage.prototype.setItem = original;
});
```

In `App.test.tsx`:
- **`stubFetch`:**
  - replace the `/api/projects` branches with
    `if (path === "/api/v1/projects" && init?.method === "POST") return response({ project_id: "project_002", name: "Other", created_at: "", updated_at: "" });`
    and
    `if (path === "/api/v1/projects") return response({ items: projects });`;
  - add `if (path.includes("/workflows?") || path.endsWith("/workflows")) return response({ items: [], next_cursor: null });`
    and
    `if (path.includes("/edit-documents?")) return response({ items: [{ document_id: "document_001", revision: 1, updated_at: "", label: "Heading", imported: true }], next_cursor: null });`;
  - change the `projects` fixture rows to
    `{ project_id: "project_001", name: "Project", created_at: "", updated_at: "" }`, in the
    declaration and in `afterEach`.
- **`afterEach`:** add `window.history.replaceState(null, "", "/"); localStorage.clear();`.
- **Delete** the test "creating a blank workflow keeps a local draft…" (the feature is removed).
- **Navigation:** in "workspace navigation identifies…", nav items are now links. Rewrite it:
  ```tsx
  test("workspace navigation identifies the active page and Creator Studio lists the project's drafts", async () => {
    stubFetch();
    const { default: App } = await import("./App");
    render(<App />);
    const nav = screen.getByRole("navigation", { name: "Workspace" });
    expect(within(nav).getByRole("link", { name: "Workflows" }).getAttribute("aria-current")).toBe("page");
    await userEvent.setup().click(within(nav).getByRole("link", { name: "Creator Studio" }));
    expect(await screen.findByRole("button", { name: /Heading/ })).toBeDefined();
    expect(window.location.pathname).toBe("/studio");
    expect(createCalls).toBe(0);
  });
  ```
- **`openContentSet`:** use `screen.getByRole("link", { name: "Content Set" })`.
- **"Open in Studio only inspects…":** after `resumeDraft`, add
  `expect(window.location.pathname).toBe("/studio/project_001/document_001");`. Back now leads
  to the drafts list, so replace the last line with
  `expect(await screen.findByRole("heading", { level: 1, name: "Creator Studio" })).toBeDefined();`.
- **"Resolve source items in Studio…":** the dialog name becomes "Resolve source items".
- **New test**, the deep link reload (Review Focus):
  ```tsx
  test("a reloaded Studio deep link renders without Content Set state", async () => {
    stubFetch();
    window.history.replaceState(null, "", "/studio/project_001/document_001");
    const { default: App } = await import("./App");
    render(<App />);
    expect(await screen.findByLabelText("Heading")).toBeDefined();
    expect(inspectBodies).toHaveLength(0);
  });
  ```
- **New test**, the stale active project (Review Focus):
  ```tsx
  test("a stored project that no longer exists falls back to the first project", async () => {
    stubFetch();
    localStorage.setItem("thoth.activeProject", "deleted_project");
    const { default: App } = await import("./App");
    render(<App />);
    await waitFor(() => expect(localStorage.getItem("thoth.activeProject")).toBe("project_001"));
  });
  ```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd dashboard && bun test src/lib/active-project.test.ts src/App.test.tsx`
Expected: FAIL. `./active-project` cannot be resolved, and the App has no links or routes.

- [ ] **Step 3: Implement the hook, the switcher, and the search**

`dashboard/src/lib/active-project.ts`:
```ts
import { useCallback, useState } from "react";

const KEY = "thoth.activeProject";

function stored(): string | null {
  try { return globalThis.localStorage?.getItem(KEY) ?? null; } catch { return null; }
}

/** The active project, remembered per browser; storage failures keep it in memory only. */
export function useActiveProject(): [string | null, (id: string | null) => void] {
  const [projectId, setProjectId] = useState<string | null>(stored);
  const set = useCallback((id: string | null) => {
    setProjectId(id);
    try {
      if (id) localStorage.setItem(KEY, id);
      else localStorage.removeItem(KEY);
    } catch {
      // A per-viewer convenience: a blocked storage only forgets it on reload.
    }
  }, []);
  return [projectId, set];
}
```

In `ProjectSwitcher.tsx`:
- import `controlPlaneClient` and `type Project` from `@/api/control-plane` instead of
  `createProject`, `listProjects` and `ProjectRecord`;
- replace every `ProjectRecord` with `Project` and every `.id` on a project with `.project_id`;
- the load effect becomes:
  ```tsx
  useEffect(() => {
    controlPlaneClient.listProjects().then((ps) => {
      setProjects(ps);
      onProjectsChanged?.(ps);
      if (ps.length && !ps.some((p) => p.project_id === projectId)) onSelect(ps[0].project_id);
    }, () => setError("Projects could not be loaded."));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  ```
- `confirmCreate` calls `controlPlaneClient.createProject(name)`.

In `DashboardSearch.tsx`:
- `projects: Project[]`, `workflows?: WorkflowRun[]`, `onNavigate: (path: string) => void`;
- `project.id` becomes `project.project_id`;
- the static entries become
  `[["/workflows", "From source to content set", Workflow, "Workflow"], ["/profiles", "Creator profiles", UserRound, "Profiles"], ["/discovery", "Discovery", Compass, "Research"]]`;
- the no-match label list changes to the same new label.

- [ ] **Step 4: Rewrite `App.tsx`**

Replace the whole file with:
```tsx
import { useEffect, useState, type ReactNode } from "react";
import { BrowserRouter, Navigate, NavLink, Route, Routes, useLocation, useNavigate, useParams } from "react-router";
import { RunForm } from "@/components/RunForm";
import { JobList } from "@/components/JobList";
import { JobMonitor } from "@/components/JobMonitor";
import { ProfileStudio } from "@/components/ProfileStudio";
import { ProjectSwitcher } from "@/components/ProjectSwitcher";
import { Discovery } from "@/components/Discovery";
import { ContentSet } from "@/components/ContentSet";
import { GuidedStudio } from "@/features/studio/GuidedStudio";
import { StudioImportGate } from "@/features/studio/StudioImportGate";
import { StudioDocumentsPage } from "@/features/studio/StudioDocumentsPage";
import { WorkflowsPage } from "@/features/workflows/WorkflowsPage";
import { WorkflowDetailPage } from "@/features/workflows/WorkflowDetailPage";
import { SourceAccounts } from "@/components/SourceAccounts";
import { SourceProxies } from "@/components/SourceProxies";
import { sourceAccountsClient } from "@/api/source-accounts";
import { controlPlaneClient, type Project, type StudioSourceProjection, type WorkflowRun } from "@/api/control-plane";
import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { CircleHelp, Clapperboard, Compass, Feather, KeyRound, Layers, Terminal, UserRound, Workflow } from "lucide-react";
import { DashboardSearch } from "@/components/DashboardSearch";
import { WorkspaceMenu } from "@/components/WorkspaceMenu";
import { PenDialog } from "@/components/PenDialog";
import { useActiveProject } from "@/lib/active-project";
import { documentLabel } from "@/lib/document-label";

const pages = {
  workflows: { path: "/workflows", label: "Workflows", eyebrow: "Workspace / 01", description: "Launch, track, and review your production runs.", icon: Workflow },
  discovery: { path: "/discovery", label: "Discover the next story", eyebrow: "Research / 02", description: "Turn signals into a focused production brief.", icon: Compass },
  contentset: { path: "/content-set", label: "Content Set", eyebrow: "Production / 03", description: "A source-backed brief, ready to shape in Creator Studio.", icon: Layers },
  profiles: { path: "/profiles", label: "Profiles", eyebrow: "Identity / 04", description: "Keep every production consistent with a reusable creative voice.", icon: UserRound },
  runs: { path: "/legacy", label: "Legacy Console", eyebrow: "Operations / 05", description: "Inspect jobs, review outputs, and intervene when a run needs attention.", icon: Terminal },
  studio: { path: "/studio", label: "Creator Studio", eyebrow: "Create / 06", description: "Your Studio drafts in this project.", icon: Clapperboard },
  accounts: { path: "/accounts", label: "Source Accounts", eyebrow: "Access / 07", description: "Logged-in sessions that acquisition rotates through, per platform.", icon: KeyRound },
  proxies: { path: "/accounts/proxies", label: "Proxies", eyebrow: "Access / 07", description: "Dedicated proxies for source accounts. Each proxy serves one account.", icon: KeyRound },
} as const;
type PageKey = keyof typeof pages;
const NAV: [PageKey, string][] = [["workflows", "Workflows"], ["discovery", "Discovery"], ["contentset", "Content Set"], ["profiles", "Profiles"], ["runs", "Legacy console"], ["studio", "Creator Studio"], ["accounts", "Source Accounts"]];

function pageFor(pathname: string): PageKey {
  if (pathname.startsWith(pages.proxies.path)) return "proxies";
  return (Object.keys(pages) as PageKey[]).find((key) => pathname.startsWith(pages[key].path)) ?? "workflows";
}

/** The router lives here, not in main.tsx, so tests render <App /> as before (ruling P5). */
export default function App() {
  return <BrowserRouter><Shell /></BrowserRouter>;
}

function Shell() {
  const navigate = useNavigate();
  const location = useLocation();
  const [projectId, setProjectId] = useActiveProject();
  const [projects, setProjects] = useState<Project[]>([]);
  const [runs, setRuns] = useState<WorkflowRun[]>([]);
  const [selectedJobId, setSelectedJobId] = useState<string | null>(null);
  const [helpOpen, setHelpOpen] = useState(false);
  const [studioImport, setStudioImport] = useState<{ projectId: string; source: StudioSourceProjection } | null>(null);
  const inStudio = /^\/studio\/[^/]+\/[^/]+/.test(location.pathname);
  const page = pageFor(location.pathname);
  const legacy = (location.state as { contentSet?: { path: string; forced: boolean } } | null)?.contentSet;
  const switcher = <ProjectSwitcher compact projectId={projectId} onSelect={setProjectId} onProjectsChanged={setProjects} />;
  const needsProject = (
    <div className="flex flex-1 flex-col items-center justify-center gap-1 p-8 text-sm text-muted-foreground">
      <p>Select or create a project to begin.</p>
      <p className="text-xs">Use “New project” at the top right.</p>
    </div>
  );

  return (
    <div data-page={inStudio ? "studio" : page} className={`dashboard-shell ${inStudio ? "dashboard-shell--studio" : ""}`}>
      <a className="dashboard-skip" href="#workspace">Skip to workspace</a>
      <header className="dashboard-topbar" hidden={inStudio}>
        <div className="dashboard-brand"><Feather aria-hidden="true" /><span>Thoth</span></div>
        <span className="dashboard-brand-caption">Creator platform</span>
        <div className="dashboard-header-tools">
          <DashboardSearch projects={projects} workflows={runs} onWorkflow={(id) => navigate(`/workflows/${encodeURIComponent(id)}`)} onProject={setProjectId} onNavigate={(path) => navigate(path)} />
          <div className="dashboard-project">{switcher}</div>
          <WorkspaceMenu onProfiles={() => navigate("/profiles")} onHelp={() => setHelpOpen(true)} />
        </div>
      </header>
      <div className="dashboard-body">
        <nav className="dashboard-sidebar" aria-label="Workspace">
          <p className="dashboard-nav-label">Workspace</p>
          {NAV.map(([id, label]) => {
            const Icon = pages[id].icon;
            return <div key={id} className={id === "runs" ? "dashboard-tools-start" : undefined}>
              {id === "runs" && <p className="dashboard-nav-label">Tools</p>}
              <NavLink to={pages[id].path} className={cn(buttonVariants({ variant: "ghost" }), "dashboard-nav-item")}
                aria-current={page === id || (id === "accounts" && page === "proxies") || (id === "studio" && inStudio) ? "page" : undefined}>
                <Icon aria-hidden="true" /><span>{label}</span>
              </NavLink>
            </div>;
          })}
          <div className="dashboard-sidebar-footer"><button type="button" onClick={() => setHelpOpen(true)}><CircleHelp aria-hidden="true" />Help & documentation</button></div>
        </nav>
        <main id="workspace" tabIndex={-1} className={`dashboard-main dashboard-page-${page}`}>
          {!inStudio && <header className="dashboard-page-heading"><div>
            <p className="dashboard-eyebrow">{pages[page].eyebrow}</p>
            <h1>{pages[page].label}</h1>
            <p>{pages[page].description}</p>
          </div><div id="dashboard-page-actions" className="pen-page-actions" /></header>}
          <Routes>
            <Route path="/" element={<Navigate to="/workflows" replace />} />
            <Route path="/workflows" element={<WorkflowsPage client={controlPlaneClient} projectId={projectId} projects={projects} onRuns={setRuns} />} />
            <Route path="/workflows/:workflowId" element={<WorkflowDetailRoute />} />
            <Route path="/discovery" element={<Discovery />} />
            <Route path="/content-set" element={<ContentSet projectId={projectId}
              onSendToRender={(path, forced) => navigate("/legacy", { state: { contentSet: { path, forced } } })}
              onOpenInStudio={(source) => { if (projectId) setStudioImport({ projectId, source }); }} />} />
            <Route path="/profiles" element={projectId ? <div className="dashboard-profile-region"><ProfileStudio projectId={projectId} onProfileChanged={() => {}} /></div> : needsProject} />
            <Route path="/legacy" element={projectId ? <>
              <div id="dashboard-legacy-metrics" />
              <RunForm projectId={projectId} onCreated={setSelectedJobId} initialContentSet={legacy?.path} initialContentSetForced={legacy?.forced}
                onConsumed={() => navigate("/legacy", { replace: true, state: null })} />
              <div className="dashboard-legacy-columns">
                <div className="dashboard-job-list"><JobList selectedId={selectedJobId} onSelect={setSelectedJobId} /></div>
                <div className="min-h-0 min-w-0 flex-1"><JobMonitor jobId={selectedJobId} /></div>
              </div>
            </> : needsProject} />
            <Route path="/studio" element={projectId ? <StudioDocumentsPage client={controlPlaneClient} projectId={projectId} /> : needsProject} />
            <Route path="/studio/:projectId/:documentId" element={<StudioDocumentRoute workspaceControls={switcher} projects={projects} />} />
            <Route path="/accounts" element={<SourceAccounts client={sourceAccountsClient} onManageProxies={() => navigate("/accounts/proxies")} />} />
            <Route path="/accounts/proxies" element={<SourceProxies client={sourceAccountsClient} onBack={() => navigate("/accounts")} />} />
            <Route path="*" element={<Navigate to="/workflows" replace />} />
          </Routes>
        </main>
      </div>
      <PenDialog open={helpOpen} onOpenChange={setHelpOpen} title="Help & shortcuts" description="Your local production workspace."><div className="pen-help-body"><h3>Production flow</h3><p>Start a workflow from a source, open its result in Creator Studio, and render. Use Profiles for reusable production settings and Legacy Console for operational job logs.</p><h3>Keyboard</h3><p>Tab moves between controls. Escape closes dialogs and menus. Space plays or pauses the Studio preview.</p><p>Provider availability and supported operations depend on your configured server.</p></div></PenDialog>
      {studioImport ? (
        <StudioImportGate client={controlPlaneClient} projectId={studioImport.projectId} source={studioImport.source}
          onClose={() => setStudioImport(null)}
          onOpen={(documentId) => {
            const target = studioImport.projectId;
            setStudioImport(null);
            navigate(`/studio/${encodeURIComponent(target)}/${encodeURIComponent(documentId)}`);
          }} />
      ) : null}
    </div>
  );
}

function WorkflowDetailRoute() {
  const { workflowId = "" } = useParams();
  return <WorkflowDetailPage client={controlPlaneClient} workflowId={workflowId} />;
}

function StudioDocumentRoute({ workspaceControls, projects }: { workspaceControls: ReactNode; projects: Project[] }) {
  const { projectId = "", documentId = "" } = useParams();
  const navigate = useNavigate();
  const [opened, setOpened] = useState(0);
  const [resolving, setResolving] = useState(false);
  const [title, setTitle] = useState<string>();
  useEffect(() => {
    let live = true;
    controlPlaneClient.getEditDocument(projectId, documentId).then((doc) => { if (live) setTitle(documentLabel(doc)); }, () => {});
    return () => { live = false; };
  }, [projectId, documentId, opened]);
  const reopen = () => { setResolving(false); setOpened((n) => n + 1); };
  return <>
    <GuidedStudio key={`${documentId}:${opened}`} client={controlPlaneClient} projectId={projectId} documentId={documentId}
      documentTitle={title} projectName={projects.find((p) => p.project_id === projectId)?.name}
      workspaceControls={workspaceControls} onBack={() => navigate("/studio")} onResolveImports={() => setResolving(true)} />
    {resolving ? <StudioImportGate client={controlPlaneClient} projectId={projectId} resumeDocumentId={documentId} onClose={reopen} onOpen={reopen} /> : null}
  </>;
}
```
If `@/lib/utils` does not export `cn`, use
`` `${buttonVariants({ variant: "ghost" })} dashboard-nav-item` ``. Delete
`WorkflowDraftDialog.tsx` and its test.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd dashboard && bun test`
Expected: the whole dashboard suite passes. Fix any other test that clicked a nav **button** to
use a **link**, and any test that relied on the removed "New workflow" button.

- [ ] **Step 6: Commit**

```bash
git add -A dashboard/src
git commit -m "feat(dashboard): URL routing and projects from the control plane"
```

### Task 14: The Vite proxy and the stack smoke checks

**Files:**
- Modify: `dashboard/vite.config.ts` (`/api` and `/health` → `http://127.0.0.1:8787`)
- Modify: `docker/test-renderer-offline.sh` (driver commands `projects` and `documents`, plus three checks)

- [ ] **Step 1: Change the proxy**

In `dashboard/vite.config.ts`, change both `"http://127.0.0.1:9090"` values to
`"http://127.0.0.1:8787"`.

- [ ] **Step 2: Add the driver commands**

In the embedded Python driver of `docker/test-renderer-offline.sh`, add before `COMMANDS = {`:
```python
def projects():
    """A project is created and listed, and its workflow list answers."""
    status, created = call("POST", "/projects", {"name": "Smoke project"})
    if status != 201:
        raise SystemExit(f"project create returned {status}")
    status, listed = call("GET", "/projects")
    if status != 200 or created["project_id"] not in {p["project_id"] for p in listed["items"]}:
        raise SystemExit("the created project is not listed")
    status, runs = call("GET", f"/projects/{created['project_id']}/workflows")
    if status != 200 or runs != {"items": [], "next_cursor": None}:
        raise SystemExit(f"project workflows returned {status}")


def documents(document_id):
    """The seeded Studio document appears in its project's document list."""
    status, page = call("GET", f"/projects/{PROJECT_ID}/edit-documents")
    if status != 200 or document_id not in {item["document_id"] for item in page["items"]}:
        raise SystemExit("the seeded document is not listed")
```
Add `"projects": projects,` and `"documents": documents,` to `COMMANDS`. Directly after the line
`echo render_output_in_the_store=true`, add:
```bash
driver projects >/dev/null || fail project_created_and_listed
echo project_created_and_listed=true
echo project_workflows_listed=true
driver documents "$document_id" >/dev/null || fail edit_documents_listed
echo edit_documents_listed=true
```
`$document_id` is the variable the script already uses for the first seeded document; reuse
that name exactly as the script defines it.

- [ ] **Step 3: Verify the script still parses**

Run: `bash -n docker/test-renderer-offline.sh`
Expected: exit 0. The full stack smoke runs in CI on the pull request.

- [ ] **Step 4: Commit**

```bash
git add dashboard/vite.config.ts docker/test-renderer-offline.sh
git commit -m "test(smoke): check projects, runs, and Studio documents in the stack"
```

### Task 15: Full verification and the records

**Files:**
- Modify: `CHANGELOG.md` (a new top entry)
- Modify: `docs/ROADMAP.md` (priority 1 done; next is priority 2)
- The SDD ledger (`.superpowers/sdd/2026-10-18-ui-foundation/progress.md`, never staged)

- [ ] **Step 1: Run every gate**

Run, and read every output:
```bash
wsl -e bash -lc 'cd /mnt/d/thoth-tmp/wt-ui-foundation && make lint && make test && make test-postgres'
cd dashboard && bun test && bun run build
uv run --project python python python/scripts/export_openapi.py && cd dashboard && bun run generate:control-plane-types && git diff --exit-code -- python/openapi.json dashboard/src/api/generated/control-plane.ts
```
Expected:
- ruff is clean;
- the full suite passes, including the Postgres tests;
- the dashboard tests and build pass;
- the contract shows no drift.

`build_cuda.bat` is not needed: no Rust file changes. Confirm with
`git diff --stat master -- crates` and expect empty output.

- [ ] **Step 2: Record**

Prepend a `CHANGELOG.md` entry headed `## 2026-10-18 - UI foundation and voice adapter`, in the
style of the entries below it. It covers:
- what shipped, by section of the spec;
- the rulings P1–P6;
- the verification counts from Step 1;
- **Next steps**:
  - the operator gates: push, PR, CI, merge, digest pin, deploy (with
    `workflow backfill`, expecting `inserted=264`), and the one-off `projects import`;
  - a post-deploy UI walk with Edge headless;
  - priority 2 (Workflow → Studio with media).

In `docs/ROADMAP.md`, mark priority 1 done with the date, and keep the rest. The file arrives
with PR #23: if `master` does not have it yet, merge `master` into this branch once PR #23 is
merged, or ledger a ruling and leave the roadmap edit to that PR's follow-up.

- [ ] **Step 3: Commit**

```bash
git add CHANGELOG.md docs/ROADMAP.md
git commit -m "docs: record the UI foundation and voice adapter"
```
