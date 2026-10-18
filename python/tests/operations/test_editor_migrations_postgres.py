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
    assert apply_editor_migrations(DATABASE_URL, MIGRATIONS) == 12
    assert apply_editor_migrations(DATABASE_URL, MIGRATIONS) == 0
    assert {"alembic_version", "studio_import_drafts", "studio_import_decisions"} <= _tables()
    assert {"source_account_policies", "source_proxies", "source_accounts"} <= _tables()
    assert "workflow_reports" in _tables()
    assert {"projects", "workflow_runs"} <= _tables()


def test_database_migrated_before_alembic_is_adopted_and_only_the_rest_applied() -> None:
    with psycopg.connect(DATABASE_URL) as connection:
        for migration in sorted(MIGRATIONS.glob("*.sql"))[:6]:
            connection.execute(migration.read_text(encoding="utf-8"))

    assert apply_editor_migrations(DATABASE_URL, MIGRATIONS) == 6
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
