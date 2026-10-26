"""Prompt Lab AI proposals on the migrated PostgreSQL schema (ORM spec 2026-10-26)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select

from tests.postgres_support import DATABASE_URL, empty_tables, needs_postgres, reset_schema
from thoth_control_plane.application.prompt_proposal_ports import (
    PromptIdempotencyConflict,
    PromptLockRevisionConflict,
    PromptPreferenceRevisionConflict,
    PromptProposalActiveGeneration,
    PromptProposalInvalidSelection,
    PromptProposalInvalidTransition,
    PromptProposalLayerLocked,
    PromptProposalStale,
    PromptProposalStoreUnavailable,
)
from thoth_control_plane.domain.prompt_proposals import (
    PromptProposal,
    SavePromptLayerLockRequest,
    SavePromptModelPreferenceRequest,
    build_prompt_changes,
)
from thoth_control_plane.infrastructure.editor_database import advisory_xact_lock, editor_sessions
from thoth_control_plane.infrastructure.editor_models import (
    ProjectPromptBindingRow,
    PromptProposalApplicationRow,
    PromptProposalChangeRow,
    PromptProposalRow,
    PromptTemplateRevisionRow,
)
from thoth_control_plane.infrastructure.prompt_proposal_repository import (
    PostgresPromptProposalRepository,
)

PROJECT = "project_a"
STAGE = "narrative_plan"
NOW = datetime(2026, 9, 13, 8, tzinfo=UTC)
IMPROVED = "Hook improved\nContext"


@pytest.fixture(scope="module")
def migrated() -> None:
    reset_schema()


@pytest.fixture
def proposals(migrated: None) -> PostgresPromptProposalRepository:
    empty_tables()
    with editor_sessions(DATABASE_URL).begin() as session:
        for revision in (1, 2):
            session.add(
                PromptTemplateRevisionRow(
                    project_id=PROJECT,
                    template_id="ptpl_001",
                    revision=revision,
                    stage_id=STAGE,
                    language="id-ID",
                    body="Hook\nContext",
                )
            )
        session.flush()
        session.add(
            ProjectPromptBindingRow(
                project_id=PROJECT,
                stage_id=STAGE,
                template_id="ptpl_001",
                template_revision=2,
                project_override="Use Indonesian",
                revision=1,
            )
        )
    return PostgresPromptProposalRepository(DATABASE_URL)


def proposal(**overrides: object) -> PromptProposal:
    values: dict[str, object] = {
        "proposal_id": "proposal_1",
        "project_id": PROJECT,
        "stage_id": STAGE,
        "kind": "improve",
        "status": "queued",
        "target_layers": ["template"],
        "source": {
            "template_id": "ptpl_001",
            "template_revision": 2,
            "binding_revision": 1,
            "template_language": "id-ID",
            "template_body": "Hook\nContext",
            "project_override": "Use Indonesian",
        },
        "target_language": None,
        "improvement_instructions": None,
        "provider_id": "novita",
        "model_id": "deepseek/deepseek-v3.1",
        "changes": [],
        "translated_template_body": None,
        "translated_project_override": None,
        "failure_code": None,
        "created_at": NOW,
        "started_at": None,
        "finished_at": None,
    }
    values.update(overrides)
    return PromptProposal.model_validate(values)


def translation(**overrides: object) -> PromptProposal:
    return proposal(
        kind="translate",
        target_layers=["template", "project_override"],
        target_language="en-US",
        **overrides,
    )


def count(table: type) -> int:
    with editor_sessions(DATABASE_URL)() as session:
        return session.scalar(select(func.count()).select_from(table)) or 0


def stored(proposal_id: str = "proposal_1") -> PromptProposalRow:
    with editor_sessions(DATABASE_URL)() as session:
        row = session.get(PromptProposalRow, proposal_id)
    assert row is not None
    return row


async def succeeded(
    proposals: PostgresPromptProposalRepository,
    source: PromptProposal | None = None,
    key: str = "idem_1",
) -> PromptProposal:
    source = source or proposal()
    await proposals.reserve_proposal(source, key, "hash_1")
    await proposals.mark_running(source.proposal_id)
    if source.kind == "translate":
        text = {"template": "Translated body", "project_override": "Translated override"}
    else:
        text = {source.target_layers[0]: IMPROVED}
    return await proposals.record_success(source.proposal_id, text)


def first_change_id() -> str:
    return build_prompt_changes("template", "Hook\nContext", IMPROVED)[0].change_id


# --- preferences and locks ---------------------------------------------------


@needs_postgres
async def test_a_model_preference_starts_at_revision_one_and_rebases_on_its_head(
    proposals: PostgresPromptProposalRepository,
) -> None:
    assert await proposals.get_preference(PROJECT, STAGE) is None
    first = await proposals.save_preference(
        PROJECT,
        STAGE,
        SavePromptModelPreferenceRequest.model_validate(
            {"provider_id": "novita", "model_id": "model_a"}
        ),
    )
    with pytest.raises(PromptPreferenceRevisionConflict) as conflict:
        await proposals.save_preference(
            PROJECT,
            STAGE,
            SavePromptModelPreferenceRequest.model_validate(
                {"provider_id": "novita", "model_id": "model_b"}
            ),
        )
    second = await proposals.save_preference(
        PROJECT,
        STAGE,
        SavePromptModelPreferenceRequest.model_validate(
            {"provider_id": "novita", "model_id": "model_b", "base_revision": 1}
        ),
    )

    assert first.revision == 1
    assert conflict.value.latest.model_id == "model_a"
    assert (second.revision, second.model_id) == (2, "model_b")
    read = await proposals.get_preference(PROJECT, STAGE)
    assert read is not None and (read.revision, read.model_id) == (2, "model_b")
    assert await proposals.get_preference("project_b", STAGE) is None


@needs_postgres
async def test_layer_locks_list_the_template_first_and_rebase_on_their_head(
    proposals: PostgresPromptProposalRepository,
) -> None:
    def request(locked: bool, base: int | None = None) -> SavePromptLayerLockRequest:
        return SavePromptLayerLockRequest.model_validate({"locked": locked, "base_revision": base})

    await proposals.save_lock(PROJECT, STAGE, "project_override", request(True))
    await proposals.save_lock(PROJECT, STAGE, "template", request(False))
    with pytest.raises(PromptLockRevisionConflict) as conflict:
        await proposals.save_lock(PROJECT, STAGE, "template", request(True))
    updated = await proposals.save_lock(PROJECT, STAGE, "template", request(True, 1))

    locks = await proposals.get_locks(PROJECT, STAGE)
    assert [(lock.layer, lock.locked, lock.revision) for lock in locks] == [
        ("template", True, 2),
        ("project_override", True, 1),
    ]
    assert conflict.value.latest.revision == 1
    assert updated.revision == 2


@needs_postgres
async def test_a_lock_save_waits_for_the_stage_lock(
    proposals: PostgresPromptProposalRepository,
) -> None:
    holder = editor_sessions(DATABASE_URL)()
    holder.begin()
    advisory_xact_lock(holder, PROJECT, STAGE)
    try:
        pending = asyncio.ensure_future(
            proposals.save_lock(
                PROJECT,
                STAGE,
                "template",
                SavePromptLayerLockRequest.model_validate({"locked": True}),
            )
        )
        await asyncio.sleep(0.5)
        assert not pending.done()
    finally:
        holder.rollback()
        holder.close()

    assert (await asyncio.wait_for(pending, timeout=10)).revision == 1


# --- reservation and the worker lifecycle -------------------------------------


@needs_postgres
async def test_a_reservation_replays_by_key_and_refuses_another_payload(
    proposals: PostgresPromptProposalRepository,
) -> None:
    reserved = await proposals.reserve_proposal(proposal(), "idem_1", "hash_1")
    replayed = await proposals.reserve_proposal(
        proposal(proposal_id="proposal_2"), "idem_1", "hash_1"
    )

    assert reserved.status == "queued"
    assert replayed.proposal_id == "proposal_1"
    with pytest.raises(PromptIdempotencyConflict):
        await proposals.reserve_proposal(proposal(proposal_id="proposal_3"), "idem_1", "hash_other")
    assert count(PromptProposalRow) == 1


@needs_postgres
async def test_a_second_active_generation_on_the_stage_is_refused(
    proposals: PostgresPromptProposalRepository,
) -> None:
    await proposals.reserve_proposal(proposal(), "idem_1", "hash_1")

    with pytest.raises(PromptProposalActiveGeneration):
        await proposals.reserve_proposal(proposal(proposal_id="proposal_2"), "idem_2", "hash_2")
    assert count(PromptProposalRow) == 1


@needs_postgres
async def test_a_reservation_supersedes_only_the_prior_succeeded_proposal(
    proposals: PostgresPromptProposalRepository,
) -> None:
    await succeeded(proposals)

    await proposals.reserve_proposal(proposal(proposal_id="proposal_2"), "idem_2", "hash_2")

    old = stored("proposal_1")
    assert (old.status, old.finished_at is not None) == ("superseded", True)
    assert stored("proposal_2").status == "queued"


@needs_postgres
async def test_a_proposal_reads_inside_its_project_only(
    proposals: PostgresPromptProposalRepository,
) -> None:
    await proposals.reserve_proposal(proposal(), "idem_1", "hash_1")

    found = await proposals.get_proposal(PROJECT, "proposal_1")

    assert found is not None and found.proposal_id == "proposal_1"
    assert await proposals.get_proposal("project_b", "proposal_1") is None
    worker = await proposals.get_proposal_for_worker("proposal_1")
    assert worker is not None and worker.project_id == PROJECT


@needs_postgres
async def test_a_worker_lookup_of_a_missing_proposal_is_the_store_error(
    proposals: PostgresPromptProposalRepository,
) -> None:
    # Pinned as the psycopg repository behaved: the not-found inside the lookup was
    # swallowed into the store error, never returned as None.
    with pytest.raises(PromptProposalStoreUnavailable):
        await proposals.get_proposal_for_worker("proposal_missing")


@needs_postgres
async def test_history_is_newest_first_clamped_and_paged(
    proposals: PostgresPromptProposalRepository,
) -> None:
    for index in range(3):
        identifier = f"proposal_{index}"
        await proposals.reserve_proposal(proposal(proposal_id=identifier), f"idem_{index}", "h")
        await proposals.mark_running(identifier)
        await proposals.record_failure(identifier, "provider_timeout")

    first = await proposals.list_proposals(PROJECT, STAGE, None, 2)
    second = await proposals.list_proposals(PROJECT, STAGE, first.next_cursor, 2)
    single = await proposals.list_proposals(PROJECT, STAGE, None, 0)

    assert [item.proposal_id for item in first.proposals] == ["proposal_2", "proposal_1"]
    assert first.next_cursor is not None
    assert [item.proposal_id for item in second.proposals] == ["proposal_0"]
    assert second.next_cursor is None
    assert len(single.proposals) == 1


@needs_postgres
async def test_running_is_stamped_once_and_illegal_moves_are_refused(
    proposals: PostgresPromptProposalRepository,
) -> None:
    await proposals.reserve_proposal(proposal(), "idem_1", "hash_1")

    running = await proposals.mark_running("proposal_1")

    assert running.status == "running"
    assert stored().started_at is not None
    with pytest.raises(PromptProposalInvalidTransition):
        await proposals.mark_running("proposal_1")


@needs_postgres
async def test_an_improvement_success_stores_its_changes(
    proposals: PostgresPromptProposalRepository,
) -> None:
    done = await succeeded(proposals)

    assert done.status == "succeeded"
    assert stored().status == "succeeded"
    assert count(PromptProposalChangeRow) == len(
        build_prompt_changes("template", "Hook\nContext", IMPROVED)
    )


@needs_postgres
async def test_a_translation_success_stores_both_translated_layers(
    proposals: PostgresPromptProposalRepository,
) -> None:
    done = await succeeded(proposals, translation())

    assert done.translated_template_body == "Translated body"
    row = stored()
    assert (row.translated_template_body, row.translated_project_override) == (
        "Translated body",
        "Translated override",
    )


@needs_postgres
async def test_a_failure_needs_a_legal_state_and_a_safe_code(
    proposals: PostgresPromptProposalRepository,
) -> None:
    await proposals.reserve_proposal(proposal(), "idem_1", "hash_1")

    with pytest.raises(ValueError, match="unsafe failure code"):
        await proposals.record_failure("proposal_1", "postgresql://secret")
    await proposals.mark_running("proposal_1")
    failed = await proposals.record_failure("proposal_1", "provider_timeout")

    assert (failed.status, failed.failure_code) == ("failed", "provider_timeout")
    with pytest.raises(PromptProposalInvalidTransition):
        await proposals.record_failure("proposal_1", "provider_timeout")


@needs_postgres
async def test_a_rejection_needs_a_succeeded_proposal(
    proposals: PostgresPromptProposalRepository,
) -> None:
    await succeeded(proposals)

    rejected = await proposals.reject_proposal(PROJECT, "proposal_1")

    assert rejected.status == "rejected"
    with pytest.raises(PromptProposalInvalidTransition):
        await proposals.reject_proposal(PROJECT, "proposal_1")


# --- apply ---------------------------------------------------------------------


@needs_postgres
async def test_an_improvement_writes_a_template_revision_binding_and_provenance(
    proposals: PostgresPromptProposalRepository,
) -> None:
    await succeeded(proposals)

    result = await proposals.apply_improvement(PROJECT, "proposal_1", [first_change_id()], "actor")

    assert (result.resulting_template_revision, result.resulting_binding_revision) == (3, 2)
    assert result.proposal.status == "applied"
    assert stored().status == "applied"
    with editor_sessions(DATABASE_URL)() as session:
        binding = session.get(ProjectPromptBindingRow, (PROJECT, STAGE))
        template = session.get(PromptTemplateRevisionRow, (PROJECT, "ptpl_001", 3))
        application = session.get(PromptProposalApplicationRow, "proposal_1")
    assert binding is not None and (binding.template_revision, binding.revision) == (3, 2)
    assert template is not None and template.body.startswith("Hook improved")
    assert application is not None
    assert (application.approving_actor, application.accepted_change_ids) == (
        "actor",
        [first_change_id()],
    )


@needs_postgres
async def test_an_override_improvement_moves_only_the_binding(
    proposals: PostgresPromptProposalRepository,
) -> None:
    await succeeded(proposals, proposal(target_layers=["project_override"]))
    change_id = build_prompt_changes("project_override", "Use Indonesian", IMPROVED)[0].change_id

    result = await proposals.apply_improvement(PROJECT, "proposal_1", [change_id], "actor")

    assert (result.resulting_template_id, result.resulting_template_revision) == ("ptpl_001", 2)
    assert result.resulting_binding_revision == 2
    assert count(PromptTemplateRevisionRow) == 2


@needs_postgres
@pytest.mark.parametrize(
    ("prepare", "change_ids", "refusal"),
    [
        ("binding_moved", None, PromptProposalStale),
        ("template_locked", None, PromptProposalLayerLocked),
        (None, ["change_unknown"], PromptProposalInvalidSelection),
    ],
)
async def test_an_improvement_fails_closed_without_any_write(
    proposals: PostgresPromptProposalRepository,
    prepare: str | None,
    change_ids: list[str] | None,
    refusal: type[Exception],
) -> None:
    await succeeded(proposals)
    if prepare == "binding_moved":
        with editor_sessions(DATABASE_URL).begin() as session:
            binding = session.get(ProjectPromptBindingRow, (PROJECT, STAGE))
            assert binding is not None
            binding.revision = 9
    if prepare == "template_locked":
        await proposals.save_lock(
            PROJECT, STAGE, "template", SavePromptLayerLockRequest.model_validate({"locked": True})
        )

    with pytest.raises(refusal):
        await proposals.apply_improvement(
            PROJECT, "proposal_1", change_ids or [first_change_id()], "actor"
        )

    assert stored().status == "succeeded"
    assert (count(PromptTemplateRevisionRow), count(PromptProposalApplicationRow)) == (2, 0)


@needs_postgres
async def test_an_improvement_needs_a_succeeded_proposal(
    proposals: PostgresPromptProposalRepository,
) -> None:
    await proposals.reserve_proposal(proposal(), "idem_1", "hash_1")
    await proposals.mark_running("proposal_1")

    with pytest.raises(PromptProposalInvalidTransition):
        await proposals.apply_improvement(PROJECT, "proposal_1", [first_change_id()], "actor")
    assert count(PromptProposalApplicationRow) == 0


@needs_postgres
async def test_a_translation_creates_a_new_template_identity(
    proposals: PostgresPromptProposalRepository,
) -> None:
    await succeeded(proposals, translation())

    result = await proposals.apply_translation(PROJECT, "proposal_1", "actor")

    assert result.resulting_template_id != "ptpl_001"
    assert (result.resulting_template_revision, result.resulting_binding_revision) == (1, 2)
    with editor_sessions(DATABASE_URL)() as session:
        binding = session.get(ProjectPromptBindingRow, (PROJECT, STAGE))
    assert binding is not None
    assert (binding.template_id, binding.project_override) == (
        result.resulting_template_id,
        "Translated override",
    )


@needs_postgres
async def test_a_translation_onto_a_locked_layer_fails_closed(
    proposals: PostgresPromptProposalRepository,
) -> None:
    await succeeded(proposals, translation())
    await proposals.save_lock(
        PROJECT,
        STAGE,
        "project_override",
        SavePromptLayerLockRequest.model_validate({"locked": True}),
    )

    with pytest.raises(PromptProposalLayerLocked):
        await proposals.apply_translation(PROJECT, "proposal_1", "actor")
    assert (count(PromptTemplateRevisionRow), count(PromptProposalApplicationRow)) == (2, 0)


@needs_postgres
async def test_an_apply_waits_for_the_stage_lock_before_locking_the_proposal(
    proposals: PostgresPromptProposalRepository,
) -> None:
    await succeeded(proposals)
    holder = editor_sessions(DATABASE_URL)()
    holder.begin()
    advisory_xact_lock(holder, PROJECT, STAGE)
    try:
        pending = asyncio.ensure_future(
            proposals.apply_improvement(PROJECT, "proposal_1", [first_change_id()], "actor")
        )
        await asyncio.sleep(0.5)
        assert not pending.done()
        # The apply holds no proposal row lock while it waits: another reader can lock it.
        with editor_sessions(DATABASE_URL).begin() as other:
            other.execute(
                select(PromptProposalRow)
                .where(PromptProposalRow.proposal_id == "proposal_1")
                .with_for_update(nowait=True)
            )
    finally:
        holder.rollback()
        holder.close()

    result = await asyncio.wait_for(pending, timeout=10)
    assert result.proposal.status == "applied"


async def test_an_unreachable_store_is_the_safe_error_without_its_address() -> None:
    unreachable = PostgresPromptProposalRepository("postgresql://user:secret@127.0.0.1:1/editor")

    with pytest.raises(
        PromptProposalStoreUnavailable, match=r"^prompt proposal store unavailable$"
    ):
        await unreachable.get_proposal(PROJECT, "proposal_1")
