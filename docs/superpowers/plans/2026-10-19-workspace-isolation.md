# Workspace Isolation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every signed-in user sees and changes only their own workspace's data, while the
operator keeps every existing record and stays the only manager of source accounts and proxies.

**Architecture:**
- The data actor becomes the workspace: `ws_bootstrap` keeps the legacy `owner` actor, and every
  other workspace uses its own ID. This alone isolates workflows, Temporal handles and run lists.
- `projects` gains a `workspace_id`. `current_actor` checks any `{project_id}` path parameter
  against the caller's workspace, so every project route is guarded in one place.
- Source-account and proxy routes take a `platform_actor` dependency.
- A structural test walks the route table, so a new route cannot skip the guard silently.

**Tech Stack:** FastAPI, SQLAlchemy 2 (sync, through `asyncio.to_thread`), Alembic over SQL files,
PostgreSQL 16, pytest, React 19 + React Router 7 + Bun tests, Caddy, Docker Compose smoke.

**Spec:** `docs/superpowers/specs/2026-10-19-workspace-isolation-design.md`

## Global Constraints

- Chat with the operator in Indonesian; every repository artifact in English.
- Commits: exactly one `git commit -m "<subject>"` (≤ 72 chars), no body, no trailer, no
  `Co-Authored-By`, no AI attribution.
- Never stage `.superpowers/`, `graphify-out/`, `.serena/`, the `.codegraph` database or
  `design/`. `docs/superpowers/**` needs `git add -f`.
- Working-copy files may be CRLF; a scripted edit must keep each file's line endings.
- No test reaches the network; no live test until the final acceptance.
- `ws_bootstrap` keeps the data actor `owner` (spec 1.1); other workspaces use their
  `workspace_id`; `actor_type` stays `user`.
- A foreign project or workflow answers **404**, identical to a missing one (spec 3.1). The
  project detail is `{"detail": "project_not_found"}`.
- A non-admin on a platform route gets the existing **403** `{"detail": "Not authorized"}`.
- Platform admin = the service key, or a user principal of `ws_bootstrap` with role `owner` or
  `admin`; platform routes also need the `admin` scope. A workspace token is never a platform
  admin.
- Media object keys do not change.

**Running the checks** (from Windows, through WSL):
- Python tests: `wsl -e bash -lc 'cd /mnt/d/thoth-tmp/wt-tenancy && make test T="<paths relative to python/>"'`
- Postgres tests: `wsl -e bash -lc 'cd /mnt/d/thoth-tmp/wt-tenancy && make test-postgres'`
- Lint: `wsl -e bash -lc 'cd /mnt/d/thoth-tmp/wt-tenancy && make format && make lint'`
- Dashboard (PowerShell or Git Bash, in `D:/thoth-tmp/wt-tenancy/dashboard`): `bun test`,
  `bunx tsc --noEmit -p tsconfig.app.json`, `bun run build`.
- OpenAPI export, in WSL from `python/`:
  `PYTHONPATH=$PWD/src $HOME/.local/bin/uv run --no-project --python 3.12 --with pydantic --with pydantic-settings --with typer --with httpx --with temporalio --with fastapi --with python-multipart --with "psycopg[binary]" --with sqlalchemy --with alembic --with "minio>=7.2.20,<8" --with agno --with "openai<3" --with cryptography --with "authlib>=1.6,<2" --with itsdangerous -- python scripts/export_openapi.py`,
  then `bun run generate:control-plane-types` in `dashboard/`.

## Review Focus

1. **`PATCH /api/v1/workflows/{id}` with another workspace's `project_id` in the body.** A
   reasonable person expects 404 `project_not_found`, never a run moved into a stranger's project.
   The body is not a path parameter, so the `current_actor` guard does not see it. Pinned in Task 3
   (`test_a_run_cannot_move_into_another_workspaces_project`).
2. **A user whose membership row is gone keeps a live session or token.** Expected: signed out
   on the next request. Pinned in Task 2 (`test_a_session_without_membership_is_signed_out`).
3. **Two first sign-ins racing on an empty installation.** Expected: exactly one `ws_bootstrap`
   owner, therefore exactly one platform admin. Pinned in Task 2 on PostgreSQL
   (`test_racing_first_users_leave_one_bootstrap_owner`).
4. **A route added later with `{project_id}` or under `/source-accounts` that forgets the guard.**
   Expected: CI fails. Pinned in Task 4 (`test_every_project_route_is_guarded`,
   `test_every_platform_route_needs_a_platform_admin`), which also fails if the route walk finds
   nothing.
5. **The smoke render driver seeds a project only through SQL, with no `projects` row.** After the
   guard, its render calls answer 404 and CI's stack smoke fails. Pinned in Task 6 (the driver seeds
   a `projects` row in `ws_bootstrap`, and the two-user isolation check runs in the smoke).

---

### Task 1: Workspace-owned projects (migration 0014, store, routes)

**Files:**
- Modify: `python/src/thoth_control_plane/auth/models.py` (helpers next to `BOOTSTRAP_WORKSPACE_ID`)
- Create: `python/migrations/editor/0014_project_workspaces.sql`
- Create: `python/migrations/editor/alembic/versions/0014_project_workspaces.py`
- Modify: `python/src/thoth_control_plane/infrastructure/run_models.py` (`ProjectRow`)
- Modify: `python/src/thoth_control_plane/infrastructure/project_store.py`
- Modify: `python/src/thoth_control_plane/api/routes/projects.py`
- Modify: `python/src/thoth_control_plane/application/workflow_runs.py:71-75,87-88,109-110,211`
- Test: `python/tests/auth/test_tenancy.py` (create)
- Test: `python/tests/infrastructure/test_project_store.py`
- Test: `python/tests/operations/test_editor_migrations_postgres.py`
- Modify callers in tests: `python/tests/api/test_workflow_runs.py`,
  `python/tests/infrastructure/test_workflow_run_store.py` (only if it calls `create`/`get`/`list`)

**Interfaces:**
- Produces (in `thoth_control_plane.auth.models`):
  - `LEGACY_ACTOR_ID = "owner"`
  - `def data_actor_id(workspace_id: str) -> str`
  - `def actor_workspace_id(actor_id: str) -> str`
- Produces (`ProjectStore`):
  - `list(workspace_id: str) -> list[Project]`
  - `get(project_id: str, workspace_id: str) -> Project | None` (None when missing **or** foreign)
  - `create(name: str, workspace_id: str) -> Project`
  - `insert_missing(project: Project) -> bool` (unchanged signature; inserts into `ws_bootstrap`)
- Produces (`WorkflowRunService._require_project(project_id: str, actor: Actor) -> None`)

- [ ] **Step 1: Write the failing tests**

Create `python/tests/auth/test_tenancy.py`:

```python
"""The data actor of a workspace, and back (spec 1.1)."""

from thoth_control_plane.auth.models import (
    BOOTSTRAP_WORKSPACE_ID,
    LEGACY_ACTOR_ID,
    actor_workspace_id,
    data_actor_id,
)


def test_the_bootstrap_workspace_keeps_the_legacy_owner_actor() -> None:
    assert data_actor_id(BOOTSTRAP_WORKSPACE_ID) == LEGACY_ACTOR_ID == "owner"
    assert actor_workspace_id("owner") == BOOTSTRAP_WORKSPACE_ID


def test_any_other_workspace_is_its_own_actor_and_back() -> None:
    assert data_actor_id("ws_abc") == "ws_abc"
    assert actor_workspace_id("ws_abc") == "ws_abc"
```

Replace the body of `python/tests/infrastructure/test_project_store.py` after the `store`
fixture with:

```python
WS = "ws_bootstrap"
OTHER = "ws_other"


def test_create_mints_a_uuid_and_trims_the_name(store: ProjectStore) -> None:
    project = store.create("  News  ", WS)
    assert project.name == "News"
    assert len(project.project_id) == 36
    assert store.get(project.project_id, WS) == project


def test_list_is_newest_updated_first(store: ProjectStore) -> None:
    first = store.create("A", WS)
    second = store.create("B", WS)
    assert [p.project_id for p in store.list(WS)] == [second.project_id, first.project_id]


def test_a_project_belongs_to_one_workspace(store: ProjectStore) -> None:
    mine = store.create("Mine", WS)
    theirs = store.create("Theirs", OTHER)
    assert [p.project_id for p in store.list(WS)] == [mine.project_id]
    assert [p.project_id for p in store.list(OTHER)] == [theirs.project_id]
    assert store.get(theirs.project_id, WS) is None
    assert store.get(mine.project_id, OTHER) is None


def test_insert_missing_keeps_the_id_lands_in_bootstrap_and_never_overwrites(
    store: ProjectStore,
) -> None:
    when = datetime(2026, 9, 1, tzinfo=UTC)
    legacy = Project(
        project_id="db766411-3cb0-47a4-9dc9-b67d22f6f34e",
        name="test",
        created_at=when,
        updated_at=when,
    )
    assert store.insert_missing(legacy) is True
    assert store.insert_missing(legacy.model_copy(update={"name": "other"})) is False
    assert store.get(legacy.project_id, WS) == legacy
    assert store.get(legacy.project_id, OTHER) is None


def test_an_absent_project_is_none(store: ProjectStore) -> None:
    assert store.get("missing", WS) is None
```

In `python/tests/operations/test_editor_migrations_postgres.py`:
- in `test_fresh_database_applies_every_revision_and_a_rerun_applies_none`, change `== 13` to
  `== 14`;
- in `test_database_migrated_before_alembic_is_adopted_and_only_the_rest_applied`, change `== 7`
  to `== 8`;
- append:

```python
def test_existing_projects_move_to_the_bootstrap_workspace() -> None:
    from thoth_control_plane.operations.editor_migrations import apply_editor_migrations as apply

    with psycopg.connect(DATABASE_URL) as connection:
        for migration in sorted(MIGRATIONS.glob("*.sql"))[:13]:
            connection.execute(migration.read_text(encoding="utf-8"))
        connection.execute(
            "INSERT INTO projects (project_id, name) VALUES ('p-legacy', 'Legacy')"
        )
    assert apply(DATABASE_URL, MIGRATIONS) == 1
    with psycopg.connect(DATABASE_URL) as connection:
        assert connection.execute(
            "SELECT workspace_id FROM projects WHERE project_id = 'p-legacy'"
        ).fetchone() == ("ws_bootstrap",)
        with pytest.raises(psycopg.errors.NotNullViolation):
            connection.execute(
                "INSERT INTO projects (project_id, name, workspace_id) VALUES ('p2', 'X', NULL)"
            )
    with psycopg.connect(DATABASE_URL) as connection:
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            connection.execute(
                "INSERT INTO projects (project_id, name, workspace_id) VALUES ('p3', 'X', 'ws_none')"
            )
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `make test T="tests/auth/test_tenancy.py tests/infrastructure/test_project_store.py"`
Expected: FAIL — `ImportError: cannot import name 'LEGACY_ACTOR_ID'`, and `TypeError` on
`create("…", WS)`.

Run: `make test-postgres`
Expected: FAIL — `assert 13 == 14` and the new test (no `workspace_id` column).

- [ ] **Step 3: Implement**

In `python/src/thoth_control_plane/auth/models.py`, directly under
`BOOTSTRAP_WORKSPACE_ID = "ws_bootstrap"`, add:

```python
#: The single data actor every record had before workspaces; it stays the bootstrap's actor.
LEGACY_ACTOR_ID = "owner"


def data_actor_id(workspace_id: str) -> str:
    """The data actor that owns a workspace's records (spec 1.1)."""
    return LEGACY_ACTOR_ID if workspace_id == BOOTSTRAP_WORKSPACE_ID else workspace_id


def actor_workspace_id(actor_id: str) -> str:
    """The workspace a data actor belongs to: the inverse of `data_actor_id`."""
    return BOOTSTRAP_WORKSPACE_ID if actor_id == LEGACY_ACTOR_ID else actor_id
```

Create `python/migrations/editor/0014_project_workspaces.sql`:

```sql
-- Projects belong to a workspace (spec 2026-10-19 workspace isolation, section 1.2). Every
-- existing project is the operator's, so it moves to the bootstrap workspace.
ALTER TABLE projects ADD COLUMN workspace_id TEXT REFERENCES workspaces (workspace_id);
UPDATE projects SET workspace_id = 'ws_bootstrap' WHERE workspace_id IS NULL;
ALTER TABLE projects ALTER COLUMN workspace_id SET NOT NULL;
CREATE INDEX projects_workspace ON projects (workspace_id, updated_at DESC);
```

Create `python/migrations/editor/alembic/versions/0014_project_workspaces.py`:

```python
"""Apply the shipped 0014_project_workspaces.sql verbatim."""

from thoth_control_plane.operations.editor_migrations import execute_sql_file

revision = "0014"
down_revision = "0013"


def upgrade() -> None:
    execute_sql_file(__file__)
```

In `python/src/thoth_control_plane/infrastructure/run_models.py`, add to `ProjectRow` after
`updated_at`:

```python
    #: No ORM foreign key and no default: the 0014 constraint is the authority, and a row must
    #: never fall into the bootstrap workspace silently. (SQLite fixtures that build only the
    #: run tables have no `workspaces` table to point at.)
    workspace_id: Mapped[str] = mapped_column(String)
```

In `python/tests/infrastructure/test_run_models.py`, the direct
`ProjectRow(project_id="p1", name="News", created_at=NOW, updated_at=NOW)` gains
`workspace_id="ws_bootstrap"`.

In `python/src/thoth_control_plane/infrastructure/project_store.py`:
- add `from thoth_control_plane.auth.models import BOOTSTRAP_WORKSPACE_ID`;
- replace `list`, `get`, `create` and `insert_missing` with:

```python
    def list(self, workspace_id: str) -> list[Project]:
        try:
            with self._sessions() as session:
                rows = session.scalars(
                    select(ProjectRow)
                    .where(ProjectRow.workspace_id == workspace_id)
                    .order_by(ProjectRow.updated_at.desc(), ProjectRow.project_id.desc())
                ).all()
        except SQLAlchemyError as error:
            raise _unavailable(error) from None
        return [_project(row) for row in rows]

    def get(self, project_id: str, workspace_id: str) -> Project | None:
        """The project, or None when it is missing or belongs to another workspace."""
        try:
            with self._sessions() as session:
                row = session.get(ProjectRow, project_id)
        except SQLAlchemyError as error:
            raise _unavailable(error) from None
        return None if row is None or row.workspace_id != workspace_id else _project(row)

    def create(self, name: str, workspace_id: str) -> Project:
        now = self._clock()
        row = ProjectRow(
            project_id=str(uuid4()),
            name=name.strip(),
            created_at=now,
            updated_at=now,
            workspace_id=workspace_id,
        )
        try:
            with self._sessions.begin() as session:
                session.add(row)
        except SQLAlchemyError as error:
            raise _unavailable(error) from None
        return _project(row)

    def insert_missing(self, project: Project) -> bool:
        """Import only: insert with the given ID into the bootstrap workspace, never overwrite."""
        try:
            with self._sessions.begin() as session:
                if session.get(ProjectRow, project.project_id) is not None:
                    return False
                session.add(ProjectRow(**project.model_dump(), workspace_id=BOOTSTRAP_WORKSPACE_ID))
                return True
        except SQLAlchemyError as error:
            raise _unavailable(error) from None
```

In `python/src/thoth_control_plane/api/routes/projects.py`, import
`from thoth_control_plane.auth.models import actor_workspace_id` and change the three calls:

```python
    return ProjectList(items=await asyncio.to_thread(store.list, actor_workspace_id(actor.actor_id)))
```

```python
    return await asyncio.to_thread(store.create, body.name, actor_workspace_id(actor.actor_id))
```

```python
    project = await asyncio.to_thread(store.get, project_id, actor_workspace_id(actor.actor_id))
```

In `python/src/thoth_control_plane/application/workflow_runs.py`, import
`from thoth_control_plane.auth.models import actor_workspace_id`, and:

```python
    async def _require_project(self, project_id: str, actor: Actor) -> None:
        """The project must exist in the caller's workspace; a foreign one is not found."""
        if self._projects is None:
            raise WorkflowRunsUnavailable("workflow_runs_unavailable")
        workspace_id = actor_workspace_id(actor.actor_id)
        if await asyncio.to_thread(self._projects.get, project_id, workspace_id) is None:
            raise ProjectNotFound
```

Update its three callers to `await self._require_project(project_id, actor)` (in `start`,
`page` and `assign`).

In the tests, every `stores[0].create("News")` in `python/tests/api/test_workflow_runs.py` becomes
`stores[0].create("News", "ws_bootstrap")`. Run `grep -rn "\.create(\"\|\.get(\|\.list()" python/tests/infrastructure/test_workflow_run_store.py`
and give any `ProjectStore` call there the `"ws_bootstrap"` argument as well.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `make test T="tests/auth/test_tenancy.py tests/infrastructure tests/api/test_projects.py tests/api/test_workflow_runs.py tests/api/test_auth_principal.py tests/test_cli.py"`
Expected: PASS.

Run: `make test-postgres`
Expected: PASS (17 tests, none skipped).

- [ ] **Step 5: Commit**

```bash
git add python/src/thoth_control_plane/auth/models.py python/migrations/editor/0014_project_workspaces.sql python/migrations/editor/alembic/versions/0014_project_workspaces.py python/src/thoth_control_plane/infrastructure/run_models.py python/src/thoth_control_plane/infrastructure/project_store.py python/src/thoth_control_plane/api/routes/projects.py python/src/thoth_control_plane/application/workflow_runs.py python/tests/auth/test_tenancy.py python/tests/infrastructure/test_project_store.py python/tests/operations/test_editor_migrations_postgres.py python/tests/api/test_workflow_runs.py python/tests/infrastructure/test_workflow_run_store.py python/tests/infrastructure/test_run_models.py
git commit -m "feat(tenancy): projects belong to a workspace (migration 0014)"
```

---

### Task 2: Membership on every request, the first-user lock, and `/me`

**Files:**
- Modify: `python/src/thoth_control_plane/auth/models.py` (`Principal.role`, `is_platform_admin`,
  `WorkspaceView`, `MeView`)
- Modify: `python/src/thoth_control_plane/infrastructure/account_store.py` (`member_role`,
  `workspace_name`, `_new_user` lock)
- Modify: `python/src/thoth_control_plane/auth/service.py` (`authenticate_session`,
  `authenticate_token`, `describe`)
- Test: `python/tests/auth/test_sign_in_service.py`
- Test: `python/tests/operations/test_editor_migrations_postgres.py`
- Test: `python/tests/api/test_me_routes.py` (only if it compares the full `/me` body)

**Interfaces:**
- Consumes: `BOOTSTRAP_WORKSPACE_ID` (existing).
- Produces:
  - `Principal(..., token_id: str | None = None, role: str | None = None)`
  - `def is_platform_admin(principal: Principal) -> bool`
  - `class WorkspaceView(StrictModel): workspace_id: str; name: str; role: str | None`
  - `MeView` gains `workspace: WorkspaceView` and `platform_admin: bool`
  - `AccountStore.member_role(user_id: str, workspace_id: str) -> str | None`
  - `AccountStore.workspace_name(workspace_id: str) -> str | None`

- [ ] **Step 1: Write the failing tests**

Append to `python/tests/auth/test_sign_in_service.py` (add `is_platform_admin` to the
`thoth_control_plane.auth.models` import):

```python
async def test_the_principal_carries_the_membership_role(service, mailer) -> None:
    first = await signed_in(service, mailer)
    principal = await service.authenticate_session(first.session_token)
    assert principal.workspace_id == BOOTSTRAP_WORKSPACE_ID
    assert principal.role == "owner"
    assert is_platform_admin(principal)


async def test_a_session_without_membership_is_signed_out(service, mailer, store) -> None:
    first = await signed_in(service, mailer)
    with store._engine.begin() as connection:
        connection.execute(text("DELETE FROM workspace_members"))
    assert await service.authenticate_session(first.session_token) is None


async def test_a_personal_token_without_membership_is_refused(service, mailer, store) -> None:
    first = await signed_in(service, mailer)
    principal = await service.authenticate_session(first.session_token)
    created = await service.create_token(principal, CreateToken(name="cli", scope="write", days=30))
    with store._engine.begin() as connection:
        connection.execute(text("DELETE FROM workspace_members"))
    assert await service.authenticate_token(created.token) is None


def test_who_is_a_platform_admin() -> None:
    def principal(workspace, role, via="session", user="usr_1"):
        return Principal(user, workspace, SCOPE_SETS["admin"], via, role=role)

    assert is_platform_admin(Principal(None, BOOTSTRAP_WORKSPACE_ID, SCOPE_SETS["admin"], "service"))
    assert is_platform_admin(principal(BOOTSTRAP_WORKSPACE_ID, "owner"))
    assert is_platform_admin(principal(BOOTSTRAP_WORKSPACE_ID, "admin", via="token"))
    assert not is_platform_admin(principal(BOOTSTRAP_WORKSPACE_ID, "member"))
    assert not is_platform_admin(principal("ws_other", "owner"))
    assert not is_platform_admin(principal(BOOTSTRAP_WORKSPACE_ID, None, via="token", user=None))


async def test_describe_names_the_workspace_and_the_admin_flag(service, mailer, store) -> None:
    first = await signed_in(service, mailer)
    principal = await service.authenticate_session(first.session_token)
    view = await service.describe(principal)
    assert view.workspace.workspace_id == BOOTSTRAP_WORKSPACE_ID
    assert view.workspace.name == "Thoth"
    assert view.workspace.role == "owner"
    assert view.platform_admin is True
    bob = store.ensure_user("bob@acme.test", "Bob")
    assert bob.workspace_id != BOOTSTRAP_WORKSPACE_ID
    bob_view = await service.describe(
        Principal(bob.user_id, bob.workspace_id, SCOPE_SETS["admin"], "session", role="owner")
    )
    assert bob_view.workspace.name == "Bob's workspace"
    assert bob_view.platform_admin is False
```

If `CreateToken` or `created.token` are named differently in `auth/models.py`, use the real
names from `test_tokens_are_scoped_limited_listed_and_revoked` in the same file.

Append to `python/tests/operations/test_editor_migrations_postgres.py`:

```python
def test_racing_first_users_leave_one_bootstrap_owner() -> None:
    import threading

    from thoth_control_plane.infrastructure.account_store import AccountStore

    apply_editor_migrations(DATABASE_URL, MIGRATIONS)
    stores = [AccountStore.connect(DATABASE_URL) for _ in range(4)]
    barrier = threading.Barrier(len(stores))

    def first_sign_in(index: int) -> None:
        barrier.wait()
        stores[index].ensure_user(f"user{index}@acme.test", f"User {index}")

    threads = [threading.Thread(target=first_sign_in, args=(i,)) for i in range(len(stores))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    with psycopg.connect(DATABASE_URL) as connection:
        owners = connection.execute(
            "SELECT count(*) FROM workspace_members WHERE workspace_id = 'ws_bootstrap'"
        ).fetchone()
        workspaces = connection.execute("SELECT count(*) FROM workspaces").fetchone()
    assert owners == (1,)
    assert workspaces == (4,)  # the bootstrap plus three personal workspaces
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `make test T="tests/auth/test_sign_in_service.py"`
Expected: FAIL — `ImportError: cannot import name 'is_platform_admin'`.

Run: `make test-postgres`
Expected: `test_racing_first_users_leave_one_bootstrap_owner` FAILS with `owners == (2,)` or more
(it can pass by luck on one run; it must pass after the fix on every run).

- [ ] **Step 3: Implement**

In `python/src/thoth_control_plane/auth/models.py`:
- add `role: str | None = None` as the last field of `Principal`, with the comment
  `# the caller's role in workspace_id; None for the service key and workspace tokens`;
- add after `Principal`:

```python
def is_platform_admin(principal: Principal) -> bool:
    """The service key, or an owner/admin of the bootstrap workspace (spec 1.3)."""
    if principal.via == "service":
        return True
    return (
        principal.user_id is not None
        and principal.workspace_id == BOOTSTRAP_WORKSPACE_ID
        and principal.role in ("owner", "admin")
    )
```

- add before `MeView`, and extend `MeView`:

```python
class WorkspaceView(StrictModel):
    workspace_id: str
    name: str
    role: str | None


class MeView(StrictModel):
    user_id: str | None
    email: str | None
    display_name: str | None
    workspace_id: str
    scopes: list[Scope]
    workspace: WorkspaceView
    platform_admin: bool
```

In `python/src/thoth_control_plane/infrastructure/account_store.py`, add under `account()`:

```python
    def member_role(self, user_id: str, workspace_id: str) -> str | None:
        """The user's role in the workspace, or None when they are not a member."""
        return self._one(
            select(MemberRow.role).where(
                MemberRow.user_id == user_id, MemberRow.workspace_id == workspace_id
            )
        )

    def workspace_name(self, workspace_id: str) -> str | None:
        return self._one(select(WorkspaceRow.name).where(WorkspaceRow.workspace_id == workspace_id))
```

In `_new_user`, replace the `ponytail` comment and the `taken = …` statement with:

```python
        # Owning the bootstrap makes a platform admin, so racing first sign-ins must serialize:
        # lock the bootstrap row, then count its members.
        session.get(WorkspaceRow, BOOTSTRAP_WORKSPACE_ID, with_for_update=True)
        taken = session.scalar(
            select(func.count())
            .select_from(MemberRow)
            .where(MemberRow.workspace_id == BOOTSTRAP_WORKSPACE_ID)
        )
```

In `python/src/thoth_control_plane/auth/service.py`:
- import `WorkspaceView` and `is_platform_admin` from `thoth_control_plane.auth.models`;
- in `authenticate_session`, after the `account is None or account.disabled` check:

```python
        role = await self._run(self._store.member_role, account.user_id, record.workspace_id)
        if role is None:  # removed from the workspace: signed out on the next request
            return None
```

  and return
  `Principal(account.user_id, record.workspace_id, ALL_SCOPES, "session", account.email, role=role)`;
- in `authenticate_token`, inside `if record.owner_kind == "user":`, after the disabled check:

```python
            role = await self._run(self._store.member_role, account.user_id, record.workspace_id)
            if role is None:
                return None
```

  initialise `role = None` next to `user_id = email = None`, and pass `role=role` to the returned
  `Principal`;
- replace `describe` with:

```python
    async def describe(self, principal: Principal) -> MeView:
        name = None
        if principal.user_id is not None:
            account = await self._run(self._store.account, principal.user_id)
            name = account.display_name if account else None
        workspace_name = await self._run(self._store.workspace_name, principal.workspace_id)
        return MeView(
            user_id=principal.user_id,
            email=principal.email,
            display_name=name,
            workspace_id=principal.workspace_id,
            scopes=sorted(principal.scopes),  # type: ignore[arg-type]
            workspace=WorkspaceView(
                workspace_id=principal.workspace_id,
                name=workspace_name or principal.workspace_id,
                role=principal.role,
            ),
            platform_admin=is_platform_admin(principal),
        )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `make test T="tests/auth tests/api/test_me_routes.py tests/api/test_auth_routes.py tests/api/test_auth_principal.py"`
Expected: PASS. If `test_me_routes.py` compares a whole `/me` body, add the two new keys
(`workspace`, `platform_admin`) with the values the service key produces:
`{"workspace_id": "ws_bootstrap", "name": <the fixture's workspace name or "ws_bootstrap">, "role": None}`
and `True`.

Run: `make test-postgres`
Expected: PASS, including `test_racing_first_users_leave_one_bootstrap_owner`. Run it three
times; it must pass every time.

- [ ] **Step 5: Commit**

```bash
git add python/src/thoth_control_plane/auth/models.py python/src/thoth_control_plane/infrastructure/account_store.py python/src/thoth_control_plane/auth/service.py python/tests/auth/test_sign_in_service.py python/tests/operations/test_editor_migrations_postgres.py python/tests/api/test_me_routes.py
git commit -m "feat(tenancy): check membership per request and lock the first user"
```

---

### Task 3: The workspace data actor, the project guard, and platform routes

**Files:**
- Modify: `python/src/thoth_control_plane/api/dependencies.py` (`current_actor`, `platform_actor`)
- Modify: `python/src/thoth_control_plane/api/routes/source_accounts.py:32,88`
- Modify: `python/tests/conftest.py` (`InMemoryWorkflowGateway` checks the owner)
- Create: `python/tests/api/open_projects.py`
- Modify: every `create_app(...)` in `python/tests/api/*.py` whose routes take `{project_id}`
  and that passes no `project_store`
- Test: `python/tests/api/test_auth_principal.py`

**Interfaces:**
- Consumes: `data_actor_id`, `actor_workspace_id` (Task 1); `ProjectStore.get(project_id, workspace_id)`
  (Task 1); `is_platform_admin`, `Principal.role` (Task 2).
- Produces:
  - `current_actor(request, principal) -> Actor` with `actor_id = data_actor_id(principal.workspace_id)`,
    raising 404 `project_not_found` for a foreign or missing `{project_id}` path parameter, and
    `ProjectStoreUnavailable` when no project store is configured
  - `platform_actor(request, principal) -> Actor`
  - test helper `OPEN_PROJECTS` in `python/tests/api/open_projects.py`

- [ ] **Step 1: Write the failing tests**

In `python/tests/api/test_auth_principal.py`, replace
`test_everyone_signed_in_acts_on_the_same_owner_data` with:

```python
def bearer_for(accounts: AccountStore, email: str, scope: str = "write") -> dict[str, str]:
    """A personal token of the user with this email, in that user's own workspace."""
    user = accounts.ensure_user(email, email.split("@")[0].title())
    secret = f"thoth_pat_{email.split('@')[0]}_{scope}"
    now = datetime.now(UTC)
    accounts.create_token(
        TokenRecord(
            f"tok_{email.split('@')[0]}_{scope}",
            "user",
            user.user_id,
            user.workspace_id,
            scope,
            secret[:16],
            scope,
            now - timedelta(days=1),
            now + timedelta(days=1),
            None,
        ),
        token_hash(secret),
    )
    return {"Authorization": f"Bearer {secret}"}


async def test_a_second_user_cannot_reach_the_first_users_project_or_workflow(
    api, accounts
) -> None:
    alice = bearer_for(accounts, "alice@acme.test")  # first user: the bootstrap workspace
    bob = bearer_for(accounts, "bob@acme.test")  # second user: a personal workspace
    project = (await api.post("/api/v1/projects", json={"name": "News"}, headers=alice)).json()
    started = await api.post(
        f"/api/v1/projects/{project['project_id']}/workflows",
        json=REQUEST,
        headers={**alice, "Idempotency-Key": "k1"},
    )
    workflow_id = started.json()["workflow_id"]

    assert (await api.get(f"/api/v1/workflows/{workflow_id}", headers=SERVICE)).status_code == 200
    foreign_project = await api.get(f"/api/v1/projects/{project['project_id']}", headers=bob)
    assert foreign_project.status_code == 404
    assert foreign_project.json() == {"detail": "project_not_found"}
    assert (await api.get("/api/v1/projects", headers=bob)).json()["items"] == []
    assert (await api.get(f"/api/v1/workflows/{workflow_id}", headers=bob)).status_code == 404
    runs = await api.get(f"/api/v1/projects/{project['project_id']}/workflows", headers=bob)
    assert runs.status_code == 404


async def test_the_data_actor_is_the_callers_workspace(api, accounts, gateway) -> None:
    alice = bearer_for(accounts, "alice@acme.test")
    bob = bearer_for(accounts, "bob@acme.test")
    await api.get("/api/v1/style-presets", headers=alice)
    assert gateway.actors[-1].actor_id == "owner"
    await api.get("/api/v1/style-presets", headers=bob)
    bob_workspace = accounts.ensure_user("bob@acme.test", "Bob").workspace_id
    assert gateway.actors[-1].actor_id == bob_workspace != "owner"


async def test_a_run_cannot_move_into_another_workspaces_project(api, accounts) -> None:
    alice = bearer_for(accounts, "alice@acme.test")
    bob = bearer_for(accounts, "bob@acme.test")
    project = (await api.post("/api/v1/projects", json={"name": "News"}, headers=alice)).json()
    started = await api.post(
        "/api/v1/workflows", json=REQUEST, headers={**bob, "Idempotency-Key": "kb"}
    )
    moved = await api.patch(
        f"/api/v1/workflows/{started.json()['workflow_id']}",
        json={"project_id": project["project_id"]},
        headers=bob,
    )
    assert moved.status_code == 404
    assert moved.json() == {"detail": "project_not_found"}


async def test_source_accounts_are_for_platform_admins_only(api, accounts) -> None:
    alice = bearer_for(accounts, "alice@acme.test", scope="admin")
    alice_write = bearer_for(accounts, "alice@acme.test", scope="write")
    bob = bearer_for(accounts, "bob@acme.test", scope="admin")
    refused = await api.get("/api/v1/source-accounts", headers=bob)
    assert refused.status_code == 403
    assert refused.json() == {"detail": "Not authorized"}
    assert (await api.get("/api/v1/source-accounts", headers=alice_write)).status_code == 403
    assert (await api.get("/api/v1/source-accounts", headers=alice)).status_code != 403
    assert (await api.get("/api/v1/source-accounts", headers=SERVICE)).status_code != 403
```

If `POST /api/v1/workflows` answers a status other than 2xx in this fixture, check the
`REQUEST` constant at the top of the file: it is the body the existing tests already start with.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `make test T="tests/api/test_auth_principal.py"`
Expected: FAIL — bob gets 200 on alice's project, `actor_id == "owner"` for bob, and bob gets a
non-403 on `/source-accounts`.

- [ ] **Step 3: Implement**

In `python/src/thoth_control_plane/api/dependencies.py`:
- add `import asyncio`;
- extend the auth import to
  `from thoth_control_plane.auth.models import ALL_SCOPES, BOOTSTRAP_WORKSPACE_ID, Principal, data_actor_id, is_platform_admin`;
- add `from thoth_control_plane.infrastructure.project_store import ProjectStoreUnavailable`;
- replace `current_actor` with:

```python
async def current_actor(
    request: Request, principal: Annotated[Principal, Depends(current_principal)]
) -> Actor:
    """The caller's workspace as the data actor (spec 1.1), and the project guard (spec 1.2).

    Every route with `{project_id}` in its path depends on this, so the project must be in the
    caller's workspace; a foreign project answers exactly like a missing one.
    """
    require_write(request, principal)
    project_id = request.path_params.get("project_id")
    if project_id is not None:
        await _require_project(request, project_id, principal.workspace_id)
    display = principal.email[:200] if principal.email else None
    return Actor(
        actor_id=data_actor_id(principal.workspace_id), actor_type="user", display_name=display
    )


async def _require_project(request: Request, project_id: str, workspace_id: str) -> None:
    store = request.app.state.project_store
    if store is None:
        raise ProjectStoreUnavailable("project_store_unavailable")
    if await asyncio.to_thread(store.get, project_id, workspace_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="project_not_found")


async def platform_actor(
    request: Request, principal: Annotated[Principal, Depends(current_principal)]
) -> Actor:
    """Platform resources (source accounts, proxies): platform admins with the admin scope."""
    if not is_platform_admin(principal) or "admin" not in principal.scopes:
        raise _forbidden()
    return await current_actor(request, principal)
```

If importing `project_store` from `dependencies` makes a circular import, import it inside
`_require_project` instead.

In `python/src/thoth_control_plane/api/routes/source_accounts.py`, change the import on line 32 to
`from thoth_control_plane.api.dependencies import platform_actor` and line 88 to
`Authorized = Annotated[Actor, Depends(platform_actor)]`. Then
`grep -n "current_actor" python/src/thoth_control_plane/api/routes/source_accounts.py` must print
nothing.

In `python/tests/conftest.py`, make `InMemoryWorkflowGateway` check the owner the way
`TemporalWorkflowGateway._authorized_handle` does:
- in `__init__`, add `self.owners: dict[str, tuple[str, str]] = {}`;
- add the method:

```python
    def _owned(self, workflow_id: str, actor: Actor) -> WorkflowSummary:
        """Like the Temporal gateway: another owner's workflow is not found."""
        summary = self._workflow(workflow_id)
        owner = self.owners.get(workflow_id)
        if owner is not None and owner != (actor.actor_type, actor.actor_id):
            raise WorkflowNotFound
        return summary
```

- in `start`, before `return summary`, add
  `self.owners[summary.workflow_id] = (actor.actor_type, actor.actor_id)`;
- in `get`, `stream_events`, `cancel`, `retry` and `record_approval`, replace
  `self._workflow(workflow_id)` with `self._owned(workflow_id, actor)`.

Workflows a test seeds directly into `gateway.workflows` have no owner entry and stay readable by
everyone, as before.

Create `python/tests/api/open_projects.py`:

```python
"""For API fixtures that predate workspaces: every project exists in the bootstrap workspace."""

from thoth_control_plane.auth.models import BOOTSTRAP_WORKSPACE_ID


class OpenProjects:
    def get(self, project_id: str, workspace_id: str) -> object | None:
        return object() if workspace_id == BOOTSTRAP_WORKSPACE_ID else None


OPEN_PROJECTS = OpenProjects()
```

Run `make test T="tests/api tests/integration"`. Every test that now fails with a 503
`project_store_unavailable` builds its app without a project store. Give that `create_app(...)`
call `project_store=OPEN_PROJECTS`, importing
`from tests.api.open_projects import OPEN_PROJECTS` (or `from .open_projects import OPEN_PROJECTS`,
matching how the file imports its other test helpers). The files expected to need it:
`test_edit_documents.py`, `test_editor_assets.py`, `test_editor_asset_uploads.py`,
`test_render_jobs.py`, `test_studio_imports.py`, `test_studio_review.py`, `test_prompt_lab.py`,
`test_prompt_proposals.py`, and `test_internal_render_jobs.py`. Do not add it to a fixture that
already passes a real `ProjectStore`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `make test T="tests/api tests/integration tests/auth tests/application tests/workflows"`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add python/src/thoth_control_plane/api/dependencies.py python/src/thoth_control_plane/api/routes/source_accounts.py python/tests/conftest.py python/tests/api
git commit -m "feat(tenancy): workspace data actor, project guard and platform routes"
```

---

### Task 4: The structural lock and cross-workspace coverage of every project route

**Files:**
- Create: `python/tests/api/test_route_isolation.py`
- Create: `python/tests/infrastructure/test_temporal_gateway_owner.py`

**Interfaces:**
- Consumes: `current_actor`, `platform_actor`, `current_principal`, `internal_renderer` (names
  of dependency callables); `bearer_for`, `REQUEST`, `SERVICE` and the `api`/`accounts`/`engine`
  fixtures pattern of `test_auth_principal.py` (Task 3).
- Produces: nothing used later.

- [ ] **Step 1: Write the tests**

Create `python/tests/infrastructure/test_temporal_gateway_owner.py`:

```python
"""The real gateway refuses a workflow whose owner is another workspace's actor."""

import pytest

from thoth_control_plane.application import WorkflowNotFound
from thoth_control_plane.domain.models import Actor, ActorSnapshot
from thoth_control_plane.infrastructure.temporal_gateway import TemporalWorkflowGateway
from thoth_control_plane.workflows.source_investigation import SourceInvestigationWorkflow

SUMMARY = object()


class Handle:
    id = "wf_x"

    def __init__(self, owner: ActorSnapshot) -> None:
        self.owner = owner

    async def query(self, query):
        return self.owner if query == SourceInvestigationWorkflow.owner_actor else SUMMARY


class Client:
    def __init__(self, owner: ActorSnapshot) -> None:
        self.handle = Handle(owner)

    def get_workflow_handle(self, workflow_id: str) -> Handle:
        return self.handle


@pytest.mark.asyncio
async def test_a_workflow_of_another_workspace_is_not_found() -> None:
    gateway = TemporalWorkflowGateway(Client(ActorSnapshot(actor_id="owner", actor_type="user")))
    with pytest.raises(WorkflowNotFound):
        await gateway.get("wf_x", actor=Actor(actor_id="ws_abc", actor_type="user"))
    assert await gateway.get("wf_x", actor=Actor(actor_id="owner", actor_type="user")) is SUMMARY
```

Create `python/tests/api/test_route_isolation.py`:

```python
"""Every project route is guarded and every platform route needs a platform admin (spec 1.4)."""

from datetime import UTC, datetime

import httpx
import pytest
from fastapi.routing import APIRoute
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from tests.api.test_auth_principal import SERVICE, bearer_for
from thoth_control_plane.api import create_app
from thoth_control_plane.auth.models import BOOTSTRAP_WORKSPACE_ID
from thoth_control_plane.config import Settings
from thoth_control_plane.infrastructure import account_models, run_models  # noqa: F401
from thoth_control_plane.infrastructure.account_models import WorkspaceRow
from thoth_control_plane.infrastructure.account_store import AccountStore
from thoth_control_plane.infrastructure.project_store import ProjectStore
from thoth_control_plane.infrastructure.source_account_models import Base

#: Routes outside /api/v1 that need no caller, and the one /api/v1 route a capability opens.
PUBLIC = {"/healthz", "/readyz"}
CAPABILITY_ONLY = {"/api/v1/projects/{project_id}/editor-assets/{asset_id}/preview"}
#: Values for path parameters other than project_id; the guard answers before they are validated.
FILLERS = {"source_key": "a" * 64}


def _walk(routes, prefix=""):
    for route in routes:
        if isinstance(route, APIRoute):
            yield prefix + route.path, route
        elif hasattr(route, "original_router"):
            inner = route.original_router.routes
            yield from _walk(inner, prefix + (route.include_context.prefix or ""))
        elif hasattr(route, "routes"):
            yield from _walk(route.routes, prefix + getattr(route, "path", ""))


def _dependencies(dependant, names=None) -> set[str]:
    names = set() if names is None else names
    for dependency in dependant.dependencies:
        names.add(getattr(dependency.call, "__name__", ""))
        _dependencies(dependency, names)
    return names


def _routes(gateway) -> list[tuple[str, APIRoute, set[str]]]:
    app = create_app(Settings(THOTH_CONTROL_PLANE_API_KEY="k"), gateway)
    found = [(path, route, _dependencies(route.dependant)) for path, route in _walk(app.routes)]
    assert len(found) >= 80, "the route walk found too few routes; the FastAPI layout changed"
    return found


def test_every_project_route_is_guarded(gateway) -> None:
    unguarded = [
        path
        for path, _route, names in _routes(gateway)
        if "{project_id}" in path and path not in CAPABILITY_ONLY and "current_actor" not in names
    ]
    assert unguarded == []


def test_every_platform_route_needs_a_platform_admin(gateway) -> None:
    platform = [
        (path, names)
        for path, _route, names in _routes(gateway)
        if path.startswith(("/api/v1/source-accounts", "/api/v1/source-proxies"))
    ]
    assert platform, "no platform route found"
    assert [path for path, names in platform if "platform_actor" not in names] == []


def test_every_other_route_has_a_caller(gateway) -> None:
    open_routes = []
    for path, _route, names in _routes(gateway):
        if path.startswith("/auth/") or path in PUBLIC or path in CAPABILITY_ONLY:
            continue
        if path.startswith("/internal/"):
            if "internal_renderer" not in names:
                open_routes.append(path)
        elif "current_principal" not in names:
            open_routes.append(path)
    assert open_routes == []


@pytest.fixture
def engine():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(
            WorkspaceRow.__table__.insert().values(
                workspace_id=BOOTSTRAP_WORKSPACE_ID, name="Thoth", created_at=datetime.now(UTC)
            )
        )
    return engine


@pytest.mark.asyncio
async def test_no_project_route_opens_another_workspaces_project(gateway, engine) -> None:
    accounts = AccountStore(engine)
    app = create_app(
        Settings(THOTH_CONTROL_PLANE_API_KEY="test-key"),
        gateway,
        project_store=ProjectStore(engine),
        account_store=accounts,
    )
    accounts.ensure_user("alice@acme.test", "Alice")  # the bootstrap owner
    bob = bearer_for(accounts, "bob@acme.test")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        project = (
            await client.post("/api/v1/projects", json={"name": "Alice"}, headers=SERVICE)
        ).json()["project_id"]
        leaks, guarded = [], 0
        for path, route, _names in _routes(gateway):
            if "{project_id}" not in path or path in CAPABILITY_ONLY:
                continue
            url = path.replace("{project_id}", project)
            while "{" in url:
                name = url[url.index("{") + 1 : url.index("}")]
                url = url.replace("{" + name + "}", FILLERS.get(name, "x1"))
            for method in route.methods - {"HEAD", "OPTIONS"}:
                body = None if method in {"GET", "DELETE"} else {}
                response = await client.request(method, url, json=body, headers=bob)
                if response.status_code < 400:
                    leaks.append((method, path, response.status_code))
                elif response.json() == {"detail": "project_not_found"}:
                    guarded += 1
    # This app configures only the project and account stores. A route whose own service
    # dependency is declared before `current_actor` may answer 503 first; that reads nothing.
    # What must never happen is a success on another workspace's project.
    assert leaks == []
    assert guarded >= 20, f"only {guarded} project calls reached the guard"
```

If `tests.api.test_auth_principal` cannot be imported as a module in this suite (no package
`__init__.py` on the path), move `bearer_for`, `SERVICE` and `REQUEST` into
`python/tests/api/open_projects.py` and import them from there in both test files.

- [ ] **Step 2: Run the tests**

Run: `make test T="tests/api/test_route_isolation.py tests/infrastructure/test_temporal_gateway_owner.py"`
Expected: PASS, because Task 3 already guards everything. To prove the lock bites, temporarily
change `Authorized = Annotated[Actor, Depends(platform_actor)]` back to `current_actor` in
`source_accounts.py` and rerun: `test_every_platform_route_needs_a_platform_admin` must FAIL.
Restore the line and rerun: PASS.

- [ ] **Step 3: Commit**

```bash
git add python/tests/api/test_route_isolation.py python/tests/infrastructure/test_temporal_gateway_owner.py python/tests/api/open_projects.py python/tests/api/test_auth_principal.py
git commit -m "test(tenancy): lock every project and platform route to its workspace"
```

---

### Task 5: The API contract and the dashboard

**Files:**
- Regenerate: `python/openapi.json`, `dashboard/src/api/generated/control-plane.ts`
- Modify: `dashboard/src/App.tsx`
- Modify: `dashboard/src/components/WorkspaceMenu.tsx`
- Test: `dashboard/src/App.test.tsx`, `dashboard/src/components/WorkspaceMenu.test.tsx`,
  `dashboard/src/features/auth/auth.test.tsx` (fixtures gain the two new `Me` fields)

**Interfaces:**
- Consumes: `MeView.workspace: {workspace_id, name, role}` and `MeView.platform_admin` (Task 2),
  surfaced as the TypeScript type `Me` from `@/api/auth`.
- Produces: nothing used later.

- [ ] **Step 1: Regenerate the contract**

Run the OpenAPI export and `bun run generate:control-plane-types` (see Global Constraints).
Expected: `git diff --stat` shows `python/openapi.json` and `control-plane.ts` changed only by
the `WorkspaceView` schema and the two `MeView` fields.

- [ ] **Step 2: Write the failing tests**

In `dashboard/src/App.test.tsx`:
- add next to the other `let` fixtures:

```tsx
const ADMIN_ME = { user_id: "usr_1", email: "alice@acme.test", display_name: "Alice", workspace_id: "ws_bootstrap", scopes: ["admin", "read", "write"], workspace: { workspace_id: "ws_bootstrap", name: "Thoth", role: "owner" }, platform_admin: true };
let me: unknown = ADMIN_ME;
```

- in `stubFetch`, change the `/auth/me` line to `if (path === "/auth/me") return response(me);`;
- in `afterEach`, add `me = ADMIN_ME;`;
- append:

```tsx
test("Source Accounts is only in the navigation of a platform admin", async () => {
  me = { ...ADMIN_ME, workspace_id: "ws_bob", workspace: { workspace_id: "ws_bob", name: "Bob's workspace", role: "owner" }, platform_admin: false };
  stubFetch();
  const { default: App } = await import("./App");
  render(<App />);
  expect(await screen.findByRole("heading", { level: 1, name: "Workflows" })).toBeDefined();
  expect(screen.queryByRole("link", { name: /Source Accounts/ })).toBeNull();
  window.history.replaceState(null, "", "/accounts");
  cleanup();
  render(<App />);
  expect(await screen.findByText("Source accounts are managed by the platform administrators.")).toBeDefined();
  expect(requested.some((path) => path.includes("/source-accounts"))).toBe(false);
});

test("an empty workspace invites the first project", async () => {
  projects = [];
  window.history.replaceState(null, "", "/studio");
  stubFetch();
  const { default: App } = await import("./App");
  render(<App />);
  expect(await screen.findByText("Create your first project")).toBeDefined();
});
```

In `dashboard/src/components/WorkspaceMenu.test.tsx` and
`dashboard/src/features/auth/auth.test.tsx`, add to each `ME` constant:
`workspace: { workspace_id: "ws_bootstrap", name: "Thoth", role: "owner" }, platform_admin: true`.
Append to `WorkspaceMenu.test.tsx`, following the file's existing render-and-open pattern:

```tsx
test("the menu names the workspace", async () => {
  render(<WorkspaceMenu me={ME} onHelp={() => {}} onTokens={() => {}} onSignOut={() => {}} />);
  await userEvent.setup().click(screen.getByRole("button", { name: "Workspace menu" }));
  expect(await screen.findByText("Thoth")).toBeDefined();
});
```

(Import `userEvent` and `screen` the way the file already does.)

- [ ] **Step 3: Run the tests to verify they fail**

Run (in `dashboard/`): `bun test src/App.test.tsx src/components/WorkspaceMenu.test.tsx`
Expected: FAIL — the Source Accounts link is present for a non-admin, "Create your first
project" is absent, and the menu does not show "Thoth".

- [ ] **Step 4: Implement**

In `dashboard/src/App.tsx`, inside `Shell`:
- after `const { me } = useAuth();` add
  `const nav = NAV.filter(([id]) => id !== "accounts" || me.platform_admin);` and map `nav`
  instead of `NAV` in the sidebar;
- add next to `needsProject`:

```tsx
  const platformOnly = (
    <div className="flex flex-1 flex-col items-center justify-center gap-1 p-8 text-sm text-muted-foreground">
      <p>Source accounts are managed by the platform administrators.</p>
    </div>
  );
```

- change `needsProject` so an empty workspace gets its own first line:

```tsx
  const needsProject = (
    <div className="flex flex-1 flex-col items-center justify-center gap-1 p-8 text-sm text-muted-foreground">
      <p>{projects.length === 0 ? "Create your first project" : "Select or create a project to begin."}</p>
      <p className="text-xs">Use “New project” at the top right.</p>
    </div>
  );
```

- guard the two account routes:

```tsx
            <Route path="/accounts" element={me.platform_admin ? <SourceAccounts client={sourceAccountsClient} onManageProxies={() => navigate("/accounts/proxies")} /> : platformOnly} />
            <Route path="/accounts/proxies" element={me.platform_admin ? <SourceProxies client={sourceAccountsClient} onBack={() => navigate("/accounts")} /> : platformOnly} />
```

In `dashboard/src/components/WorkspaceMenu.tsx`, inside `.pen-workspace-identity`, after the
`<small>` with the email, add `<small className="pen-workspace-name">{me.workspace.name}</small>`.

- [ ] **Step 5: Run the dashboard checks**

Run (in `dashboard/`): `bun test`, then `bunx tsc --noEmit -p tsconfig.app.json`, then
`bun run build`.
Expected: all pass; tsc reports 0 errors.

- [ ] **Step 6: Commit**

```bash
git add python/openapi.json dashboard/src/api/generated/control-plane.ts dashboard/src/App.tsx dashboard/src/App.test.tsx dashboard/src/components/WorkspaceMenu.tsx dashboard/src/components/WorkspaceMenu.test.tsx dashboard/src/features/auth/auth.test.tsx
git commit -m "feat(dashboard): workspace name, admin-only Source Accounts, empty state"
```

---

### Task 6: Stack smoke, documentation and records

**Files:**
- Modify: `docker/test-renderer-offline.sh` (seed a `projects` row; two-user isolation check)
- Modify: `docs/python-control-plane.md` (section "Sign-in and developer access")
- Modify: `docs/ROADMAP.md` (SaaS track row 2, and row 3's scope)
- Modify: `CHANGELOG.md` (new top entry)

**Interfaces:**
- Consumes: the whole feature.
- Produces: nothing.

- [ ] **Step 1: Seed the smoke project in the bootstrap workspace**

In `docker/test-renderer-offline.sh`, find the driver's seed that inserts into `editor_assets`
with `PROJECT_ID` (around the `INSERT INTO editor_assets` statement). Directly before it, inside the
same cursor, add:

```python
            cursor.execute(
                "INSERT INTO projects (project_id, name, workspace_id)"
                " VALUES (%s, 'Smoke project', 'ws_bootstrap') ON CONFLICT DO NOTHING",
                (PROJECT_ID,),
            )
```

Match the indentation and cursor variable name of the surrounding block.

- [ ] **Step 2: Add the two-user isolation check**

Extend the `web()` helper so a fourth argument is a JSON body: inside its Python, after the
`Authorization` header lines, add

```python
if len(sys.argv) > 4:
    request.data = sys.argv[4].encode()
    request.add_header("Content-Type", "application/json")
```

After the `developer_token_revoked=true` line, add:

```bash
# --- workspace isolation: a second user never sees the first user's project (spec 2026-10-19) ---
first_token=$(compose exec -T api thoth-control tokens create --email smoke@thoth.test --name iso --scope admin | tr -d '\r') \
    || fail workspaces_are_isolated
second_token=$(compose exec -T api thoth-control tokens create --email second@thoth.test --name iso --scope admin | tr -d '\r') \
    || fail workspaces_are_isolated
second_project=$(BODY=1 web /api/v1/projects POST "$second_token" '{"name":"Second"}' \
    | python3 -c 'import json,sys; print(json.load(sys.stdin)["project_id"])') \
    || fail workspaces_are_isolated
[ "$(web "/api/v1/projects/$second_project" GET "$second_token")" = "200" ] || fail workspaces_are_isolated
[ "$(web "/api/v1/projects/$second_project" GET "$first_token")" = "404" ] || fail workspaces_are_isolated
BODY=1 web /api/v1/projects GET "$second_token" | grep -q "Smoke project" && fail workspaces_are_isolated
[ "$(web /api/v1/source-accounts GET "$second_token")" = "403" ] || fail workspaces_are_isolated
echo workspaces_are_isolated=true
```

`smoke@thoth.test` signed up first in this smoke, so it owns `ws_bootstrap`; `second@thoth.test`
gets a personal workspace.

- [ ] **Step 3: Run the smoke locally**

Run in WSL from the worktree:
`make smoke-renderer IMAGE=<local thoth image> RENDERER_IMAGE=<renderer> WEB_IMAGE=<web>`, using
the images the branch's CI publishes, or a local build of the three Dockerfiles.
Expected: the output contains `workspaces_are_isolated=true` and every earlier check still prints
`=true`. If a local build is not possible, push the branch and read the CI stack-smoke log for the
same lines; record which one was used in the ledger.

- [ ] **Step 4: Documentation and records**

In `docs/python-control-plane.md`, at the end of "Sign-in and developer access", add:

```markdown
### Workspaces

Every user works in their own workspace. The first user of an installation owns the bootstrap
workspace, which holds every record made before workspaces existed; every later user gets a
personal workspace on their first sign-in.

- Projects belong to a workspace, and every route under `/api/v1/projects/{project_id}` answers
  404 `project_not_found` for another workspace's project, exactly as for a missing one.
- Workflows belong to their workspace's data actor: the bootstrap keeps the legacy `owner`, and
  any other workspace uses its own ID.
- Source accounts and proxies are a platform resource. Only the service key and the owners and
  admins of the bootstrap workspace manage them, with the `admin` scope; every workspace's
  workflows share the pool.
- A session or token stops working as soon as its user is no longer a member of its workspace.
```

In `docs/ROADMAP.md`, SaaS track: set sub-project 2's status to `Done 2026-10-19` (the deploy
date is filled at deploy time) and extend sub-project 3's scope cell with:
`; a per-workspace quota on source-account leases and proxy use, required before public sign-up`.

Add a new top entry to `CHANGELOG.md` titled
`## 2026-10-19 - Workspace isolation (SaaS sub-project 2)` with: spec and plan paths, branch,
what shipped (one bullet per task), the verification commands with their real results, the
rulings from the ledger, and a **Next steps** list: operator gates (push, PR, CI, merge, deploy),
the operator's second-account check, and sub-project 3 (metering, including the shared-pool
quota).

- [ ] **Step 5: Full verification**

Run: `make format && make lint`, `make test`, `make test-postgres`, and in `dashboard/`
`bun test`, `bunx tsc --noEmit -p tsconfig.app.json`, `bun run build`.
Expected: all green; record the counts.

- [ ] **Step 6: Commit**

```bash
git add docker/test-renderer-offline.sh docs/python-control-plane.md docs/ROADMAP.md CHANGELOG.md
git commit -m "docs(tenancy): smoke isolation check and record workspace isolation"
```
