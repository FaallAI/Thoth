"""Every editor ORM row matches its migrated table (ORM spec 2026-10-26, D3).

The migrations are the source of truth; this catches a model that drifts from them.
"""

from __future__ import annotations

import pytest
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql

from tests.postgres_support import DATABASE_URL, needs_postgres, reset_schema
from thoth_control_plane.infrastructure.editor_database import editor_engine
from thoth_control_plane.infrastructure.editor_models import EditorBase

pytestmark = needs_postgres


@pytest.fixture(scope="module", autouse=True)
def migrated() -> None:
    reset_schema()


def _type(sql_type: object) -> str:
    return str(sql_type.compile(dialect=postgresql.dialect()))  # type: ignore[attr-defined]


@pytest.mark.parametrize("table", EditorBase.metadata.sorted_tables, ids=lambda table: table.name)
def test_the_row_matches_the_migrated_table(table) -> None:
    inspector = inspect(editor_engine(DATABASE_URL))
    live = {column["name"]: column for column in inspector.get_columns(table.name)}

    assert set(live) == {column.name for column in table.columns}
    for column in table.columns:
        assert _type(live[column.name]["type"]) == _type(column.type), column.name
        assert live[column.name]["nullable"] == column.nullable, column.name
    primary_key = inspector.get_pk_constraint(table.name)["constrained_columns"]
    assert set(primary_key) == {column.name for column in table.primary_key.columns}
