"""A disposable, migrated editor database for the Postgres-backed repository tests.

`make test-postgres` and CI set `THOTH_TEST_EDITOR_DATABASE_URL`; CI also sets
`THOTH_REQUIRE_POSTGRES_TESTS=1`, where a skipped Postgres test is a failure.
"""

from __future__ import annotations

import os
from pathlib import Path

import psycopg
import pytest

from thoth_control_plane.infrastructure.editor_database import editor_engine
from thoth_control_plane.operations.editor_migrations import apply_editor_migrations

DATABASE_URL = os.environ.get("THOTH_TEST_EDITOR_DATABASE_URL", "")
REQUIRED = os.environ.get("THOTH_REQUIRE_POSTGRES_TESTS") == "1"
MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations" / "editor"

if REQUIRED and not DATABASE_URL:
    raise RuntimeError("THOTH_REQUIRE_POSTGRES_TESTS=1 but THOTH_TEST_EDITOR_DATABASE_URL is unset")

needs_postgres = pytest.mark.skipif(
    not DATABASE_URL, reason="THOTH_TEST_EDITOR_DATABASE_URL points at a disposable Postgres"
)


def reset_schema() -> None:
    """Rebuild the public schema from the shipped migrations."""
    with psycopg.connect(DATABASE_URL, autocommit=True) as connection:
        connection.execute("DROP SCHEMA public CASCADE")
        connection.execute("CREATE SCHEMA public")
    apply_editor_migrations(DATABASE_URL, MIGRATIONS)
    # Pooled connections may hold plans for the dropped tables.
    editor_engine(DATABASE_URL).dispose()


def empty_tables() -> None:
    """Empty every migrated table, keeping the schema and the migration record."""
    with psycopg.connect(DATABASE_URL, autocommit=True) as connection:
        tables = [
            row[0]
            for row in connection.execute(
                "SELECT tablename FROM pg_tables "
                "WHERE schemaname = 'public' AND tablename <> 'alembic_version'"
            )
        ]
        if tables:
            connection.execute(f"TRUNCATE {', '.join(tables)} RESTART IDENTITY CASCADE")
