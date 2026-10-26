"""The one active render slot and its history on the migrated PostgreSQL schema
(ORM spec 2026-10-26)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import func, select

from tests.postgres_support import DATABASE_URL, empty_tables, needs_postgres, reset_schema
from thoth_control_plane.application.render_job_ports import (
    InvalidRenderCursor,
    RenderBusy,
    RenderIdempotencyConflict,
    RenderJobNotFound,
    RenderPersistenceError,
)
from thoth_control_plane.domain.render_jobs import (
    InvalidRenderTransition,
    RenderJob,
    RenderJobEvent,
)
from thoth_control_plane.infrastructure import render_job_repository
from thoth_control_plane.infrastructure.editor_database import advisory_xact_lock, editor_sessions
from thoth_control_plane.infrastructure.editor_models import (
    EditDocumentRevisionRow,
    RenderJobIdempotencyRow,
    RenderJobRow,
)
from thoth_control_plane.infrastructure.render_job_repository import (
    RENDER_LOCK_KEY,
    RENDER_LOCK_NAMESPACE,
    PostgresRenderJobRepository,
)

NOW = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)
LATER = datetime(2026, 9, 20, 12, 5, tzinfo=UTC)
CHECKSUM = "sha256:" + "a" * 64
HASH = "b" * 64
OTHER_HASH = "c" * 64
OUTPUT_PATH = "renders/rj_1/output.mp4"


@pytest.fixture(scope="module")
def migrated() -> None:
    reset_schema()


@pytest.fixture
def renders(migrated: None) -> PostgresRenderJobRepository:
    empty_tables()
    with editor_sessions(DATABASE_URL).begin() as session:
        for project_id, document_id in (("project_alpha", "doc_1"), ("project_beta", "doc_2")):
            session.add(
                EditDocumentRevisionRow(
                    project_id=project_id, document_id=document_id, revision=7, document_json={}
                )
            )
    return PostgresRenderJobRepository(DATABASE_URL)


def output_facts() -> dict[str, Any]:
    return {
        "media_type": "video/mp4",
        "size_bytes": 2_048_000,
        "checksum": CHECKSUM,
        "codec": "h264",
        "width": 1080,
        "height": 1920,
        "fps": 30.0,
        "duration_seconds": 20.0,
        "has_audio": True,
    }


def job(**overrides: object) -> RenderJob:
    payload: dict[str, object] = {
        "render_job_id": "rj_1",
        "project_id": "project_alpha",
        "document_id": "doc_1",
        "document_revision": 7,
        "dispatch_id": "dispatch_1",
        "template_id": "vertical_text_story",
        "template_version": 1,
        "preset_id": "standard_vertical_mp4_v1",
        "renderer_version": "remotion-4.0.538",
        "status": "preparing",
        "last_event_sequence": 0,
        "created_by": "user_1",
        "created_at": NOW,
        "provenance": {
            "document_revision": 7,
            "template_id": "vertical_text_story",
            "template_version": 1,
            "preset_id": "standard_vertical_mp4_v1",
            "renderer_version": "remotion-4.0.538",
            "asset_checksums": [{"asset_id": "asset_main", "checksum": CHECKSUM}],
            "output": None,
        },
    }
    payload.update(overrides)
    return RenderJob.model_validate(payload)


def beta(**overrides: object) -> RenderJob:
    return job(render_job_id="rj_2", project_id="project_beta", document_id="doc_2", **overrides)


def completed_job(**overrides: object) -> RenderJob:
    provenance = dict(job().provenance.model_dump(mode="json"))
    provenance["output"] = output_facts()
    payload: dict[str, object] = {
        "status": "completed",
        "last_event_sequence": 6,
        "finished_at": LATER,
        "output_relative_path": OUTPUT_PATH,
        "output": output_facts(),
        "provenance": provenance,
    }
    payload.update(overrides)
    return job(**payload)


def event(**overrides: object) -> RenderJobEvent:
    payload: dict[str, object] = {
        "render_job_id": "rj_1",
        "dispatch_id": "dispatch_1",
        "sequence": 1,
        "status": "rendering",
        "occurred_at": LATER,
    }
    payload.update(overrides)
    return RenderJobEvent.model_validate(payload)


def rows(table: type) -> int:
    with editor_sessions(DATABASE_URL)() as session:
        return session.scalar(select(func.count()).select_from(table)) or 0


async def reserve(
    renders: PostgresRenderJobRepository, record: RenderJob, key: str = "rk_1", digest: str = HASH
) -> RenderJob:
    return await renders.reserve(record, idempotency_key=key, payload_hash=digest)


# --- reserve --------------------------------------------------------------


@needs_postgres
async def test_a_reservation_records_the_job_and_its_key(
    renders: PostgresRenderJobRepository,
) -> None:
    reserved = await reserve(renders, job())

    assert reserved == job()
    assert await renders.get_internal(render_job_id="rj_1") == job()
    assert (rows(RenderJobRow), rows(RenderJobIdempotencyRow)) == (1, 1)


@needs_postgres
async def test_a_reservation_waits_for_the_render_lock(
    renders: PostgresRenderJobRepository,
) -> None:
    holder = editor_sessions(DATABASE_URL)()
    holder.begin()
    advisory_xact_lock(holder, RENDER_LOCK_NAMESPACE, RENDER_LOCK_KEY)
    try:
        pending = asyncio.ensure_future(reserve(renders, job()))
        await asyncio.sleep(0.5)
        assert not pending.done()
    finally:
        holder.rollback()
        holder.close()

    assert await asyncio.wait_for(pending, timeout=10) == job()


@needs_postgres
async def test_an_identical_replay_wins_even_while_another_project_is_active(
    renders: PostgresRenderJobRepository,
) -> None:
    first = await reserve(renders, job())

    replayed = await reserve(renders, job(render_job_id="rj_retry"))

    assert replayed == first
    assert rows(RenderJobRow) == 1


@needs_postgres
async def test_the_same_key_for_another_request_conflicts(
    renders: PostgresRenderJobRepository,
) -> None:
    await reserve(renders, job())

    with pytest.raises(RenderIdempotencyConflict):
        await reserve(renders, job(render_job_id="rj_other"), digest=OTHER_HASH)


@needs_postgres
async def test_an_occupied_slot_is_busy_with_the_active_job(
    renders: PostgresRenderJobRepository,
) -> None:
    await reserve(renders, job())

    with pytest.raises(RenderBusy) as busy:
        await reserve(renders, beta(), key="rk_2")

    assert (busy.value.active_render_job_id, busy.value.active_project_id) == (
        "rj_1",
        "project_alpha",
    )
    assert rows(RenderJobRow) == 1


@needs_postgres
async def test_the_active_slot_index_is_the_authority_even_when_the_read_raced(
    renders: PostgresRenderJobRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    await reserve(renders, job())
    # Simulate a racing reader that saw a free slot.
    monkeypatch.setattr(
        render_job_repository,
        "_active",
        lambda: select(RenderJobRow).where(RenderJobRow.render_job_id == "rj_none"),
    )

    with pytest.raises(RenderBusy):
        await reserve(renders, beta(), key="rk_2")
    assert rows(RenderJobRow) == 1


@needs_postgres
async def test_find_replay_reads_without_writing(renders: PostgresRenderJobRepository) -> None:
    assert (
        await renders.find_replay(
            project_id="project_alpha", idempotency_key="rk_1", payload_hash=HASH
        )
        is None
    )
    await reserve(renders, job())

    found = await renders.find_replay(
        project_id="project_alpha", idempotency_key="rk_1", payload_hash=HASH
    )
    assert found == job()
    with pytest.raises(RenderIdempotencyConflict):
        await renders.find_replay(
            project_id="project_alpha", idempotency_key="rk_1", payload_hash=OTHER_HASH
        )
    assert rows(RenderJobRow) == 1


# --- reads ----------------------------------------------------------------


@needs_postgres
async def test_a_read_is_project_scoped_and_rebuilds_output_from_provenance(
    renders: PostgresRenderJobRepository,
) -> None:
    await reserve(renders, completed_job())

    found = await renders.get(project_id="project_alpha", render_job_id="rj_1")

    assert found == completed_job()
    assert found is not None and found.output is not None
    assert found.output.checksum == CHECKSUM
    assert await renders.get(project_id="project_beta", render_job_id="rj_1") is None
    assert await renders.get_internal(render_job_id="rj_1") == completed_job()
    assert await renders.get_internal(render_job_id="rj_missing") is None


@needs_postgres
async def test_the_active_slot_reads_across_every_project(
    renders: PostgresRenderJobRepository,
) -> None:
    assert await renders.get_active() is None
    await reserve(renders, completed_job())
    assert await renders.get_active() is None

    await reserve(renders, beta(status="rendering"), key="rk_2")

    active = await renders.get_active()
    assert active is not None and active.render_job_id == "rj_2"


@needs_postgres
async def test_history_is_newest_first_bounded_and_keyset_paginated(
    renders: PostgresRenderJobRepository,
) -> None:
    for minute, render_job_id in enumerate(("rj_a", "rj_b", "rj_c")):
        await reserve(
            renders,
            completed_job(render_job_id=render_job_id, created_at=NOW + timedelta(minutes=minute)),
            key=f"rk_{render_job_id}",
        )

    first = await renders.list(project_id="project_alpha", limit=2, cursor=None)
    second = await renders.list(project_id="project_alpha", limit=2, cursor=first.next_cursor)

    assert [entry.render_job_id for entry in first.jobs] == ["rj_c", "rj_b"]
    assert first.next_cursor is not None
    assert [entry.render_job_id for entry in second.jobs] == ["rj_a"]
    assert second.next_cursor is None
    assert (await renders.list(project_id="project_beta", limit=2, cursor=None)).jobs == ()


@needs_postgres
async def test_the_history_limit_is_clamped_to_the_server_bound(
    renders: PostgresRenderJobRepository,
) -> None:
    for minute in range(2):
        await reserve(
            renders,
            completed_job(render_job_id=f"rj_{minute}", created_at=NOW + timedelta(minutes=minute)),
            key=f"rk_{minute}",
        )

    single = await renders.list(project_id="project_alpha", limit=0, cursor=None)
    every = await renders.list(project_id="project_alpha", limit=5_000, cursor=None)

    assert len(single.jobs) == 1 and single.next_cursor is not None
    assert len(every.jobs) == 2 and every.next_cursor is None


async def test_an_unreadable_cursor_is_refused_before_any_database_call() -> None:
    unreachable = PostgresRenderJobRepository("postgresql://user:secret@127.0.0.1:1/editor")

    for cursor in ("not a cursor!", "bm90LWEtY3Vyc29y"):
        with pytest.raises(InvalidRenderCursor):
            await unreachable.list(project_id="project_alpha", limit=10, cursor=cursor)


async def test_an_unexpected_failure_is_the_safe_error_without_the_address() -> None:
    unreachable = PostgresRenderJobRepository("postgresql://user:secret@127.0.0.1:1/editor")

    with pytest.raises(RenderPersistenceError) as failure:
        await unreachable.get_active()
    assert "secret" not in str(failure.value)


# --- lifecycle -------------------------------------------------------------


@needs_postgres
async def test_an_event_persists_its_transition(renders: PostgresRenderJobRepository) -> None:
    await reserve(renders, job())

    updated = await renders.apply_event(
        render_job_id="rj_1", event=event(sequence=1, status="rendering"), now=LATER
    )

    assert (updated.status, updated.started_at) == ("rendering", LATER)
    assert await renders.get_internal(render_job_id="rj_1") == updated


@needs_postgres
async def test_an_event_that_changes_nothing_writes_nothing(
    renders: PostgresRenderJobRepository,
) -> None:
    await reserve(renders, job(status="rendering", last_event_sequence=4, started_at=NOW))

    unchanged = await renders.apply_event(
        render_job_id="rj_1", event=event(sequence=4, status="finalizing"), now=LATER
    )

    assert unchanged.status == "rendering"
    stored = await renders.get_internal(render_job_id="rj_1")
    assert stored is not None and stored.status == "rendering"


@needs_postgres
async def test_an_event_never_reopens_a_terminal_job(renders: PostgresRenderJobRepository) -> None:
    cancelled = job(status="cancelled", last_event_sequence=6, finished_at=LATER)
    await reserve(renders, cancelled)

    unchanged = await renders.apply_event(
        render_job_id="rj_1", event=event(sequence=9, status="rendering"), now=LATER
    )

    assert unchanged.status == "cancelled"
    assert await renders.get_internal(render_job_id="rj_1") == cancelled


@needs_postgres
async def test_an_event_for_a_missing_job_is_not_found(
    renders: PostgresRenderJobRepository,
) -> None:
    with pytest.raises(RenderJobNotFound, match=r"^render job not found$"):
        await renders.apply_event(render_job_id="rj_missing", event=event(), now=LATER)


@needs_postgres
async def test_a_cancel_request_is_recorded_once(renders: PostgresRenderJobRepository) -> None:
    await reserve(renders, job(status="rendering", last_event_sequence=2, started_at=NOW))

    first, requested = await renders.mark_cancel_requested(
        project_id="project_alpha", render_job_id="rj_1", now=NOW
    )
    second, again = await renders.mark_cancel_requested(
        project_id="project_alpha", render_job_id="rj_1", now=LATER
    )

    assert (requested, again) == (True, False)
    assert first.cancel_requested_at == second.cancel_requested_at == NOW
    with pytest.raises(RenderJobNotFound):
        await renders.mark_cancel_requested(
            project_id="project_beta", render_job_id="rj_1", now=NOW
        )


@needs_postgres
async def test_a_cancel_request_is_refused_for_a_terminal_job(
    renders: PostgresRenderJobRepository,
) -> None:
    await reserve(renders, completed_job())

    with pytest.raises(InvalidRenderTransition):
        await renders.mark_cancel_requested(
            project_id="project_alpha", render_job_id="rj_1", now=LATER
        )


@needs_postgres
async def test_cleanup_marks_a_terminal_job_once_and_keeps_the_audit_row(
    renders: PostgresRenderJobRepository,
) -> None:
    await reserve(renders, completed_job())

    cleaned = await renders.mark_cleaned(
        project_id="project_alpha", render_job_id="rj_1", now=LATER
    )
    again = await renders.mark_cleaned(project_id="project_alpha", render_job_id="rj_1", now=NOW)

    assert cleaned.artifacts_cleaned_at == again.artifacts_cleaned_at == LATER
    assert cleaned.output_relative_path == OUTPUT_PATH
    assert cleaned.provenance.output is not None
    assert await renders.get_internal(render_job_id="rj_1") == cleaned


@needs_postgres
async def test_cleanup_is_refused_while_the_job_is_active(
    renders: PostgresRenderJobRepository,
) -> None:
    await reserve(renders, job(status="rendering", started_at=NOW))

    with pytest.raises(InvalidRenderTransition):
        await renders.mark_cleaned(project_id="project_alpha", render_job_id="rj_1", now=LATER)


@needs_postgres
async def test_the_expired_scan_is_bounded_to_old_active_rows(
    renders: PostgresRenderJobRepository,
) -> None:
    await reserve(renders, completed_job(render_job_id="rj_done"), key="rk_done")
    await reserve(renders, job(status="rendering", started_at=NOW))

    expired = await renders.list_expired_active(deadline=LATER, limit=10)
    fresh = await renders.list_expired_active(deadline=NOW, limit=10)

    assert [entry.render_job_id for entry in expired] == ["rj_1"]
    assert fresh == ()
