"""Style templates on the migrated PostgreSQL schema (spec 2026-11-10)."""

from __future__ import annotations

import pytest

from tests.postgres_support import DATABASE_URL, empty_tables, needs_postgres, reset_schema
from thoth_control_plane.domain.style_templates import BUILT_IN_STYLES
from thoth_control_plane.infrastructure.editor_database import editor_sessions
from thoth_control_plane.infrastructure.editor_models import StyleTemplateRow
from thoth_control_plane.infrastructure.style_template_repository import (
    PostgresStyleTemplateRepository,
)

pytestmark = [needs_postgres, pytest.mark.asyncio]


@pytest.fixture(scope="module")
def migrated() -> None:
    reset_schema()


@pytest.fixture
def styles(migrated: None) -> PostgresStyleTemplateRepository:
    empty_tables()
    return PostgresStyleTemplateRepository(DATABASE_URL)


def store(workspace_id: str, template_id: str, revision: int, name: str) -> None:
    body = BUILT_IN_STYLES["style_a"].model_copy(
        update={"template_id": template_id, "revision": revision, "name": name}
    )
    with editor_sessions(DATABASE_URL).begin() as session:
        session.add(
            StyleTemplateRow(
                workspace_id=workspace_id,
                template_id=template_id,
                revision=revision,
                body=body.model_dump(mode="json"),
            )
        )


async def test_built_ins_are_listed_for_any_workspace(
    styles: PostgresStyleTemplateRepository,
) -> None:
    listed = await styles.list_for("ws_any")
    assert [style.template_id for style in listed] == ["style_a", "style_b"]


async def test_a_workspace_sees_its_own_latest_revision_only(
    styles: PostgresStyleTemplateRepository,
) -> None:
    store("ws_one", "style_mine", 1, "Mine v1")
    store("ws_one", "style_mine", 2, "Mine v2")
    store("ws_two", "style_theirs", 1, "Theirs")
    listed = {style.template_id: style for style in await styles.list_for("ws_one")}
    assert set(listed) == {"style_a", "style_b", "style_mine"}
    assert listed["style_mine"].name == "Mine v2"
    assert await styles.get("style_theirs", "ws_one") is None
    assert (await styles.get("style_b", "ws_one")) == BUILT_IN_STYLES["style_b"]


async def test_two_workspaces_may_use_the_same_template_id(
    styles: PostgresStyleTemplateRepository,
) -> None:
    # Deferred minor (2026-11-10): a template id is a workspace's own, so the key holds it.
    store("ws_one", "style_news", 1, "One's news")
    store("ws_two", "style_news", 1, "Two's news")
    one = await styles.get("style_news", "ws_one")
    two = await styles.get("style_news", "ws_two")
    assert one is not None and two is not None
    assert (one.name, two.name) == ("One's news", "Two's news")
