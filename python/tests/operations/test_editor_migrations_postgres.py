from __future__ import annotations

import os
from pathlib import Path

import psycopg
import psycopg.types.json
import pytest

from thoth_control_plane.operations.editor_migrations import apply_editor_migrations

MIGRATIONS = Path(__file__).resolve().parents[2] / "migrations" / "editor"
DATABASE_URL = os.environ.get("THOTH_TEST_EDITOR_DATABASE_URL", "")

#: CI and `make test-postgres` set this: there a skipped Postgres test is a failure.
REQUIRED = os.environ.get("THOTH_REQUIRE_POSTGRES_TESTS") == "1"

if REQUIRED and not DATABASE_URL:
    raise RuntimeError("THOTH_REQUIRE_POSTGRES_TESTS=1 but THOTH_TEST_EDITOR_DATABASE_URL is unset")

pytestmark = pytest.mark.skipif(
    not DATABASE_URL, reason="THOTH_TEST_EDITOR_DATABASE_URL points at a disposable Postgres"
)


@pytest.fixture(autouse=True)
def empty_schema() -> None:
    with psycopg.connect(DATABASE_URL, autocommit=True) as connection:
        connection.execute("DROP SCHEMA public CASCADE")
        connection.execute("CREATE SCHEMA public")


def _tables() -> set[str]:
    with psycopg.connect(DATABASE_URL) as connection:
        rows = connection.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
        )
        return {row[0] for row in rows}


def test_fresh_database_applies_every_revision_and_a_rerun_applies_none() -> None:
    assert apply_editor_migrations(DATABASE_URL, MIGRATIONS) == 17
    assert apply_editor_migrations(DATABASE_URL, MIGRATIONS) == 0
    assert {"alembic_version", "studio_import_drafts", "studio_import_decisions"} <= _tables()
    assert {"source_account_policies", "source_proxies", "source_accounts"} <= _tables()
    assert "workflow_reports" in _tables()
    assert {"projects", "workflow_runs"} <= _tables()


def test_database_migrated_before_alembic_is_adopted_and_only_the_rest_applied() -> None:
    with psycopg.connect(DATABASE_URL) as connection:
        for migration in sorted(MIGRATIONS.glob("*.sql"))[:6]:
            connection.execute(migration.read_text(encoding="utf-8"))

    assert apply_editor_migrations(DATABASE_URL, MIGRATIONS) == 11
    assert {"studio_import_drafts", "studio_import_decisions"} <= _tables()


def test_schema_that_is_not_a_chain_prefix_is_refused_untouched() -> None:
    with psycopg.connect(DATABASE_URL) as connection:
        connection.execute("CREATE TABLE studio_review_events (id integer)")

    with pytest.raises(RuntimeError, match="editor migration failed"):
        apply_editor_migrations(DATABASE_URL, MIGRATIONS)
    assert _tables() == {"studio_review_events"}


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


def _body(location: str) -> dict:
    with psycopg.connect(DATABASE_URL) as connection:
        row = connection.execute(
            "SELECT body FROM workflow_reports WHERE location = %s", (location,)
        ).fetchone()
    return row[0]


def test_an_escaped_backslash_before_u0000_is_kept_and_adjacent_nuls_are_dropped() -> None:
    from thoth_control_plane.infrastructure.report_store import ReportStore

    apply_editor_migrations(DATABASE_URL, MIGRATIONS)
    store = ReportStore.connect(DATABASE_URL)
    escaped = rb'{"c": "\\u0000"}'
    store.put("reports/wf_esc/source-report.json", "source_report", escaped)
    store.put("reports/wf_two/source-report.json", "source_report", rb'{"c": "a\u0000\u0000b"}')
    store.put("reports/wf_mix/source-report.json", "source_report", rb'{"c": "\\\u0000x"}')

    assert store.get("reports/wf_esc/source-report.json") == escaped
    assert _body("reports/wf_esc/source-report.json") == {"c": "\\u0000"}
    assert _body("reports/wf_two/source-report.json") == {"c": "ab"}
    assert _body("reports/wf_mix/source-report.json") == {"c": "\\x"}


def test_a_lone_surrogate_is_stored_exactly_with_no_body_while_a_pair_has_one() -> None:
    from thoth_control_plane.infrastructure.report_store import ReportStore

    apply_editor_migrations(DATABASE_URL, MIGRATIONS)
    store = ReportStore.connect(DATABASE_URL)
    lone = rb'{"t": "\ud83d"}'
    store.put("reports/wf_lone/source-report.json", "source_report", lone)
    store.put("reports/wf_pair/source-report.json", "source_report", rb'{"t": "a\ud83d\ude00b"}')

    assert store.get("reports/wf_lone/source-report.json") == lone
    assert _body("reports/wf_lone/source-report.json") is None
    assert _body("reports/wf_pair/source-report.json") == {"t": "a\U0001f600b"}


def test_timestamps_default_to_now() -> None:
    apply_editor_migrations(DATABASE_URL, MIGRATIONS)
    with psycopg.connect(DATABASE_URL) as connection:
        connection.execute(
            "INSERT INTO workflow_reports (location, workflow_id, kind, content, sha256, "
            "size_bytes) VALUES ('reports/wf_d/a.json', 'wf_d', 'source_report', '{}', "
            "repeat('0', 64), 2)"
        )


@pytest.mark.parametrize("content", [b'{"x": NaN}'])
def test_content_jsonb_would_refuse_is_invalid_never_unavailable(content: bytes) -> None:
    from thoth_control_plane.infrastructure.report_store import ReportInvalid, ReportStore

    apply_editor_migrations(DATABASE_URL, MIGRATIONS)
    store = ReportStore.connect(DATABASE_URL)
    with pytest.raises(ReportInvalid):
        store.put("reports/wf_bad/source-report.json", "source_report", content)
    assert store.get("reports/wf_bad/source-report.json") is None


def test_a_second_put_replaces_the_row_and_regenerates_body() -> None:
    from thoth_control_plane.infrastructure.report_store import ReportStore

    apply_editor_migrations(DATABASE_URL, MIGRATIONS)
    store = ReportStore.connect(DATABASE_URL)
    location = "reports/wf_two_put/source-report.json"
    store.put(location, "source_report", b'{"v": 1}')
    store.put(location, "source_report", b'{"v": 2}')

    assert store.get(location) == b'{"v": 2}'
    assert _body(location) == {"v": 2}


def test_insert_missing_never_overwrites_on_postgres() -> None:
    from thoth_control_plane.infrastructure.report_store import ReportStore

    apply_editor_migrations(DATABASE_URL, MIGRATIONS)
    store = ReportStore.connect(DATABASE_URL)
    location = "reports/wf_keep/source-report.json"
    assert store.insert_missing(location, "source_report", b'{"v": 1}') is True
    assert store.insert_missing(location, "source_report", b'{"v": 2}') is False
    assert store.get(location) == b'{"v": 1}'
    assert _body(location) == {"v": 1}


def _revision(project: str, document: str, revision: int, heading: str, when: str) -> None:
    body = {"clips": [{"kind": "text", "heading": heading}], "revision": revision}
    with psycopg.connect(DATABASE_URL) as connection:
        connection.execute(
            "INSERT INTO edit_document_revisions"
            " (project_id, document_id, revision, document_json, created_at)"
            " VALUES (%s, %s, %s, %s, %s)",
            (project, document, revision, psycopg.types.json.Jsonb(body), when),
        )


@pytest.mark.asyncio
async def test_studio_documents_list_their_latest_revision_newest_first() -> None:
    from thoth_control_plane.infrastructure.editor_repository import (
        PostgresEditDocumentRepository,
    )

    apply_editor_migrations(DATABASE_URL, MIGRATIONS)
    _revision("p1", "doc_old", 1, "Old", "2026-10-01T00:00:00Z")
    _revision("p1", "doc_new", 1, "First title", "2026-10-02T00:00:00Z")
    _revision("p1", "doc_new", 2, "Second title", "2026-10-03T00:00:00Z")
    _revision("p2", "doc_other", 1, "Elsewhere", "2026-10-04T00:00:00Z")
    repository = PostgresEditDocumentRepository(DATABASE_URL)

    first = await repository.list_documents(project_id="p1", limit=1, cursor=None)
    assert [(i.document_id, i.revision, i.label) for i in first.items] == [
        ("doc_new", 2, "Second title")
    ]
    assert first.items[0].imported is False
    rest = await repository.list_documents(project_id="p1", limit=1, cursor=first.next_cursor)
    assert [i.document_id for i in rest.items] == ["doc_old"]
    assert rest.next_cursor is None


def test_workflow_runs_round_trip_their_summary_and_page_on_postgres() -> None:
    import json
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import create_engine
    from sqlalchemy.engine import make_url

    from thoth_control_plane.domain import Actor, WorkflowSummary
    from thoth_control_plane.infrastructure.project_store import ProjectStore
    from thoth_control_plane.infrastructure.workflow_run_store import WorkflowRunStore

    apply_editor_migrations(DATABASE_URL, MIGRATIONS)
    engine = create_engine(make_url(DATABASE_URL).set(drivername="postgresql+psycopg"))
    start = datetime(2026, 10, 18, tzinfo=UTC)
    ticks = iter(start + timedelta(seconds=n) for n in range(100))
    projects = ProjectStore(engine)
    runs = WorkflowRunStore(engine, clock=lambda: next(ticks))
    owner = Actor(actor_id="owner", actor_type="user")
    project = projects.create("News", "ws_bootstrap")
    for name in ("wf_a", "wf_b"):
        summary = WorkflowSummary.model_validate_json(
            json.dumps(
                {
                    "workflow_id": name,
                    "status": "running",
                    "created_at": start.isoformat(),
                    "updated_at": start.isoformat(),
                    "source": {"display_url": "https://x.test/v", "platform": "tiktok"},
                    "stages": [],
                }
            )
        )
        runs.record_start(summary, project_id=project.project_id, actor=owner)

    first, cursor = runs.page(
        project_id=project.project_id, unassigned=False, actor=owner, cursor=None, limit=1
    )
    rest, end = runs.page(
        project_id=project.project_id, unassigned=False, actor=owner, cursor=cursor, limit=1
    )
    assert [r.workflow_id for r in first + rest] == ["wf_b", "wf_a"]
    assert end is None
    assert first[0].summary is not None and first[0].summary.status.value == "running"


@pytest.mark.asyncio
async def test_a_malformed_studio_document_cursor_raises_invalid_cursor() -> None:
    from thoth_control_plane.domain.cursors import InvalidCursor
    from thoth_control_plane.infrastructure.editor_repository import (
        PostgresEditDocumentRepository,
    )

    apply_editor_migrations(DATABASE_URL, MIGRATIONS)
    with pytest.raises(InvalidCursor):
        await PostgresEditDocumentRepository(DATABASE_URL).list_documents(
            project_id="p1", limit=5, cursor="%%"
        )


def test_accounts_tables_exist_with_the_bootstrap_workspace() -> None:
    apply_editor_migrations(DATABASE_URL, MIGRATIONS)
    assert {
        "workspaces",
        "users",
        "user_identities",
        "workspace_members",
        "sessions",
        "trusted_devices",
        "email_challenges",
        "access_tokens",
        "auth_events",
    } <= _tables()
    with psycopg.connect(DATABASE_URL) as connection:
        rows = connection.execute("SELECT workspace_id, name FROM workspaces").fetchall()
        assert rows == [("ws_bootstrap", "Thoth")]
        with pytest.raises(psycopg.errors.CheckViolation):
            connection.execute(
                "INSERT INTO users (user_id, email, display_name, created_at)"
                " VALUES ('usr_1', 'Mixed@Case.test', 'A', now())"
            )


def test_account_store_round_trips_on_postgres() -> None:
    from datetime import UTC, datetime, timedelta

    from thoth_control_plane.infrastructure.account_store import AccountStore

    apply_editor_migrations(DATABASE_URL, MIGRATIONS)
    store = AccountStore.connect(DATABASE_URL)
    user = store.ensure_user("a@acme.test", "A")
    assert user.workspace_id == "ws_bootstrap"
    later = datetime.now(UTC) + timedelta(hours=1)
    store.create_session(user.user_id, user.workspace_id, "h", later)
    assert store.live_session("h").user_id == user.user_id
    store.record_event("sign_in", "ok", user_id=user.user_id)
    store.create_challenge("chl_pg", user.user_id, "c", "hmac", later)
    assert [store.claim_attempt("c").attempts for _ in range(5)] == [1, 2, 3, 4, 5]
    assert store.claim_attempt("c") is None


def test_existing_projects_move_to_the_bootstrap_workspace(tmp_path: Path) -> None:
    import shutil

    before = tmp_path / "editor"
    shutil.copytree(MIGRATIONS, before)
    (before / "0014_project_workspaces.sql").unlink()
    (before / "alembic" / "versions" / "0014_project_workspaces.py").unlink()
    (before / "0015_metering.sql").unlink()
    (before / "alembic" / "versions" / "0015_metering.py").unlink()
    (before / "0016_billing.sql").unlink()
    (before / "alembic" / "versions" / "0016_billing.py").unlink()
    (before / "0017_studio_import_decision_reason.sql").unlink()
    (before / "alembic" / "versions" / "0017_studio_import_decision_reason.py").unlink()
    assert apply_editor_migrations(DATABASE_URL, before) == 13
    with psycopg.connect(DATABASE_URL) as connection:
        connection.execute("INSERT INTO projects (project_id, name) VALUES ('p-legacy', 'Legacy')")
    assert apply_editor_migrations(DATABASE_URL, MIGRATIONS) == 4
    with psycopg.connect(DATABASE_URL) as connection:
        assert connection.execute(
            "SELECT workspace_id FROM projects WHERE project_id = 'p-legacy'"
        ).fetchone() == ("ws_bootstrap",)
        with pytest.raises(psycopg.errors.NotNullViolation):
            connection.execute(
                "INSERT INTO projects (project_id, name, workspace_id) VALUES ('p2', 'X', NULL)"
            )
    with (
        psycopg.connect(DATABASE_URL) as connection,
        pytest.raises(psycopg.errors.ForeignKeyViolation),
    ):
        connection.execute(
            "INSERT INTO projects (project_id, name, workspace_id) VALUES ('p3', 'X', 'ws_none')"
        )


def test_racing_first_users_leave_one_bootstrap_owner() -> None:
    import threading

    from thoth_control_plane.infrastructure.account_store import AccountStore

    apply_editor_migrations(DATABASE_URL, MIGRATIONS)
    stores = [AccountStore.connect(DATABASE_URL) for _ in range(4)]
    barrier = threading.Barrier(len(stores))
    errors: list[BaseException] = []

    def first_sign_in(index: int) -> None:
        barrier.wait()
        try:
            stores[index].ensure_user(f"user{index}@acme.test", f"User {index}")
        except BaseException as error:  # a thread's exception would otherwise vanish
            errors.append(error)

    threads = [threading.Thread(target=first_sign_in, args=(i,)) for i in range(len(stores))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []
    with psycopg.connect(DATABASE_URL) as connection:
        owners = connection.execute(
            "SELECT count(*) FROM workspace_members WHERE workspace_id = 'ws_bootstrap'"
        ).fetchone()
        workspaces = connection.execute("SELECT count(*) FROM workspaces").fetchone()
    assert owners == (1,)
    assert workspaces == (4,)  # the bootstrap plus three personal workspaces


def test_a_second_user_gets_a_personal_workspace_on_postgres() -> None:
    from thoth_control_plane.infrastructure.account_store import AccountStore

    apply_editor_migrations(DATABASE_URL, MIGRATIONS)
    store = AccountStore.connect(DATABASE_URL)
    assert store.ensure_user("first@acme.test", "First").workspace_id == "ws_bootstrap"
    second = store.ensure_user("second@acme.test", "Second")
    assert second.workspace_id.startswith("ws_") and second.workspace_id != "ws_bootstrap"
    assert store.member_role(second.user_id, second.workspace_id) == "owner"
    assert store.workspace_name(second.workspace_id) == "Second's workspace"


def test_metering_tables_and_the_reserve_column_exist() -> None:
    apply_editor_migrations(DATABASE_URL, MIGRATIONS)
    assert {"usage_events", "workspace_quotas", "unit_prices"} <= _tables()
    with psycopg.connect(DATABASE_URL) as connection:
        connection.execute(
            "INSERT INTO usage_events (event_id, workspace_id, kind, key, quantity, unit)"
            " VALUES ('use_1', 'ws_bootstrap', 'account_lease', 'instagram', 1, 'session')"
        )
        with pytest.raises(psycopg.errors.CheckViolation):
            connection.execute(
                "INSERT INTO usage_events (event_id, workspace_id, kind, key, quantity, unit)"
                " VALUES ('use_2', 'ws_bootstrap', 'teleport', 'x', 1, 'session')"
            )
    with psycopg.connect(DATABASE_URL) as connection, pytest.raises(psycopg.errors.CheckViolation):
        connection.execute(
            "INSERT INTO source_account_policies (platform, mode, operator_reserve_percent,"
            " updated_at) VALUES ('instagram', 'always', 101, now())"
        )


def test_billing_tables_exist_with_the_free_plan() -> None:
    apply_editor_migrations(DATABASE_URL, MIGRATIONS)
    assert {"plans", "subscriptions", "invoices", "allowance_uses", "exchange_rates"} <= _tables()
    with psycopg.connect(DATABASE_URL) as connection:
        assert connection.execute(
            "SELECT plan_id, name, price_idr, workflows_per_period, videos_per_period,"
            " period_days, active FROM plans"
        ).fetchall() == [("free", "Free", 0, 3, 1, 30, True)]
        with pytest.raises(psycopg.errors.CheckViolation):
            connection.execute(
                "INSERT INTO plans (plan_id, name, price_idr, workflows_per_period,"
                " videos_per_period, period_days, active) VALUES ('x', 'X', -1, 1, 1, 30, true)"
            )
    with psycopg.connect(DATABASE_URL) as connection, pytest.raises(psycopg.errors.UniqueViolation):
        for _ in range(2):
            connection.execute(
                "INSERT INTO allowance_uses (use_id, workspace_id, kind, ref, created_at)"
                " VALUES (gen_random_uuid()::text, 'ws_bootstrap', 'workflow', 'r1', now())"
            )
