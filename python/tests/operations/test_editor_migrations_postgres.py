from __future__ import annotations

import os
from pathlib import Path

import psycopg
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
    assert apply_editor_migrations(DATABASE_URL, MIGRATIONS) == 11
    assert apply_editor_migrations(DATABASE_URL, MIGRATIONS) == 0
    assert {"alembic_version", "studio_import_drafts", "studio_import_decisions"} <= _tables()
    assert {"source_account_policies", "source_proxies", "source_accounts"} <= _tables()
    assert "workflow_reports" in _tables()


def test_database_migrated_before_alembic_is_adopted_and_only_the_rest_applied() -> None:
    with psycopg.connect(DATABASE_URL) as connection:
        for migration in sorted(MIGRATIONS.glob("*.sql"))[:6]:
            connection.execute(migration.read_text(encoding="utf-8"))

    assert apply_editor_migrations(DATABASE_URL, MIGRATIONS) == 5
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
