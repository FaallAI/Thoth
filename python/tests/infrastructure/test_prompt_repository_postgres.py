"""Prompt Lab revisions and bindings on the migrated PostgreSQL schema (ORM spec 2026-10-26)."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from sqlalchemy import select

from tests.postgres_support import DATABASE_URL, empty_tables, needs_postgres, reset_schema
from thoth_control_plane.application.ports import (
    PromptBindingNotFound,
    PromptBindingRevisionConflict,
    PromptTemplateNotFound,
    PromptTemplateRevisionConflict,
)
from thoth_control_plane.domain.prompts import (
    ProjectPromptBinding,
    PromptTemplateRevision,
    SaveProjectPromptBindingRequest,
)
from thoth_control_plane.infrastructure.editor_database import advisory_xact_lock, editor_sessions
from thoth_control_plane.infrastructure.editor_models import ProjectPromptBindingRow
from thoth_control_plane.infrastructure.prompt_repository import (
    PostgresPromptLabRepository,
    PromptLabPersistenceError,
)

PROJECT = "project_a"
TEMPLATE = "ptpl_001"
STAGE = "narrative_plan"


@pytest.fixture(scope="module")
def migrated() -> None:
    reset_schema()


@pytest.fixture
def prompts(migrated: None) -> PostgresPromptLabRepository:
    empty_tables()
    return PostgresPromptLabRepository(DATABASE_URL)


async def save(
    prompts: PostgresPromptLabRepository,
    base_revision: int | None = None,
    *,
    project_id: str = PROJECT,
    template_id: str = TEMPLATE,
    stage_id: str = STAGE,
    body: str = "Original prompt",
) -> PromptTemplateRevision:
    return await prompts.save_template(
        project_id=project_id,
        template_id=template_id,
        base_revision=base_revision,
        stage_id=stage_id,  # type: ignore[arg-type]
        language="id-ID",
        body=body,
    )


def binding(**overrides: Any) -> SaveProjectPromptBindingRequest:
    payload: dict[str, Any] = {
        "template_id": TEMPLATE,
        "template_revision": 1,
        "project_override": "Use Indonesian",
    }
    return SaveProjectPromptBindingRequest.model_validate(payload | overrides)


@needs_postgres
async def test_a_new_template_starts_at_revision_one_per_project(
    prompts: PostgresPromptLabRepository,
) -> None:
    first = await save(prompts)
    elsewhere = await save(prompts, project_id="project_b")

    assert (first.revision, elsewhere.revision) == (1, 1)
    assert first.body == "Original prompt"


@needs_postgres
async def test_creating_an_existing_template_conflicts_with_its_head(
    prompts: PostgresPromptLabRepository,
) -> None:
    await save(prompts)
    head = await save(prompts, 1, body="Second")

    with pytest.raises(PromptTemplateRevisionConflict) as conflict:
        await save(prompts)
    assert conflict.value.latest == head


@needs_postgres
async def test_a_stale_base_revision_conflicts_with_the_head(
    prompts: PostgresPromptLabRepository,
) -> None:
    await save(prompts)
    head = await save(prompts, 1, body="Second")

    with pytest.raises(PromptTemplateRevisionConflict) as conflict:
        await save(prompts, 1, body="Late")
    assert conflict.value.latest == head


@needs_postgres
async def test_a_base_revision_for_an_unknown_template_is_not_found(
    prompts: PostgresPromptLabRepository,
) -> None:
    with pytest.raises(PromptTemplateNotFound):
        await save(prompts, 1)


@needs_postgres
async def test_template_heads_are_the_latest_revision_of_each_template_of_the_stage(
    prompts: PostgresPromptLabRepository,
) -> None:
    await save(prompts)
    await save(prompts, 1, body="Second")
    await save(prompts, template_id="ptpl_002", body="Other")
    await save(prompts, template_id="ptpl_visual", stage_id="visual_plan")

    heads = await prompts.list_template_heads(project_id=PROJECT, stage_id=STAGE)

    assert [(head.template_id, head.revision, head.body) for head in heads] == [
        (TEMPLATE, 2, "Second"),
        ("ptpl_002", 1, "Other"),
    ]


@needs_postgres
async def test_a_template_revision_is_read_only_inside_its_project(
    prompts: PostgresPromptLabRepository,
) -> None:
    saved = await save(prompts)

    found = await prompts.get_template_revision(
        project_id=PROJECT, template_id=TEMPLATE, revision=1
    )
    foreign = await prompts.get_template_revision(
        project_id="project_b", template_id=TEMPLATE, revision=1
    )
    missing = await prompts.get_template_revision(
        project_id=PROJECT, template_id=TEMPLATE, revision=9
    )

    assert found == saved
    assert foreign is None and missing is None


@needs_postgres
async def test_a_template_save_waits_for_its_template_lock(
    prompts: PostgresPromptLabRepository,
) -> None:
    holder = editor_sessions(DATABASE_URL)()
    holder.begin()
    advisory_xact_lock(holder, PROJECT, TEMPLATE)
    try:
        pending = asyncio.ensure_future(save(prompts))
        await asyncio.sleep(0.5)
        assert not pending.done()
    finally:
        holder.rollback()
        holder.close()

    assert (await asyncio.wait_for(pending, timeout=10)).revision == 1


@needs_postgres
async def test_a_first_binding_is_revision_one_and_reads_back_per_project_and_stage(
    prompts: PostgresPromptLabRepository,
) -> None:
    await save(prompts)

    saved = await prompts.save_binding(project_id=PROJECT, stage_id=STAGE, request=binding())

    assert saved == ProjectPromptBinding(
        project_id=PROJECT,
        stage_id=STAGE,
        template_id=TEMPLATE,
        template_revision=1,
        project_override="Use Indonesian",
        revision=1,
    )
    assert await prompts.get_binding(project_id=PROJECT, stage_id=STAGE) == saved
    assert await prompts.get_binding(project_id="project_b", stage_id=STAGE) is None
    assert await prompts.get_binding(project_id=PROJECT, stage_id="visual_plan") is None


@needs_postgres
async def test_a_binding_update_moves_its_revision_and_its_clock(
    prompts: PostgresPromptLabRepository,
) -> None:
    await save(prompts)
    await save(prompts, 1, body="Second")
    await prompts.save_binding(project_id=PROJECT, stage_id=STAGE, request=binding())
    with editor_sessions(DATABASE_URL)() as session:
        before = session.scalar(select(ProjectPromptBindingRow.updated_at))

    updated = await prompts.save_binding(
        project_id=PROJECT,
        stage_id=STAGE,
        request=binding(template_revision=2, project_override=None, base_revision=1),
    )

    assert (updated.revision, updated.template_revision, updated.project_override) == (2, 2, None)
    assert await prompts.get_binding(project_id=PROJECT, stage_id=STAGE) == updated
    with editor_sessions(DATABASE_URL)() as session:
        after = session.scalar(select(ProjectPromptBindingRow.updated_at))
    assert before is not None and after is not None and after > before


@needs_postgres
async def test_binding_conflicts_and_absences_are_typed(
    prompts: PostgresPromptLabRepository,
) -> None:
    await save(prompts)

    with pytest.raises(PromptBindingNotFound):
        await prompts.save_binding(
            project_id=PROJECT, stage_id=STAGE, request=binding(base_revision=1)
        )
    first = await prompts.save_binding(project_id=PROJECT, stage_id=STAGE, request=binding())
    with pytest.raises(PromptBindingRevisionConflict) as unbased:
        await prompts.save_binding(project_id=PROJECT, stage_id=STAGE, request=binding())
    with pytest.raises(PromptBindingRevisionConflict) as stale:
        await prompts.save_binding(
            project_id=PROJECT, stage_id=STAGE, request=binding(base_revision=7)
        )
    assert unbased.value.latest == stale.value.latest == first


@needs_postgres
async def test_a_binding_to_an_unknown_template_revision_is_the_safe_error(
    prompts: PostgresPromptLabRepository,
) -> None:
    with pytest.raises(PromptLabPersistenceError, match=r"^prompt lab persistence unavailable$"):
        await prompts.save_binding(
            project_id=PROJECT, stage_id=STAGE, request=binding(template_revision=5)
        )
    assert await prompts.get_binding(project_id=PROJECT, stage_id=STAGE) is None


async def test_an_unreachable_store_is_the_safe_error_without_its_address() -> None:
    repository = PostgresPromptLabRepository("postgresql://user:secret@127.0.0.1:1/editor")

    with pytest.raises(PromptLabPersistenceError) as failure:
        await repository.get_binding(project_id=PROJECT, stage_id=STAGE)
    assert str(failure.value) == "prompt lab persistence unavailable"
    assert "secret" not in repr(failure.value.args)


def test_conflict_errors_are_safe() -> None:
    template = PromptTemplateRevision(
        project_id=PROJECT,
        template_id=TEMPLATE,
        revision=1,
        stage_id=STAGE,
        language="id-ID",
        body="Original prompt",
    )
    bound = ProjectPromptBinding(
        project_id=PROJECT,
        stage_id=STAGE,
        template_id=TEMPLATE,
        template_revision=1,
        project_override="Use Indonesian",
        revision=1,
    )

    assert str(PromptTemplateRevisionConflict(template)) == "prompt template revision conflict"
    assert str(PromptBindingRevisionConflict(bound)) == "prompt binding revision conflict"


def test_repository_implements_the_application_seam() -> None:
    for method in (
        "list_template_heads",
        "get_template_revision",
        "save_template",
        "get_binding",
        "save_binding",
    ):
        assert callable(getattr(PostgresPromptLabRepository, method))
