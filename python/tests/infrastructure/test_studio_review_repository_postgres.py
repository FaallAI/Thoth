"""Append-only Studio review events on the migrated PostgreSQL schema (ORM spec 2026-10-26)."""

from __future__ import annotations

import asyncio
import inspect
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import func, select

from tests.domain.edit_document_v2_fixtures import clip_by_id, document_v2_payload
from tests.postgres_support import DATABASE_URL, empty_tables, needs_postgres, reset_schema
from thoth_control_plane.application.studio_review_ports import (
    InvalidStudioReviewPage,
    StudioReviewDocumentNotFound,
    StudioReviewFrameOutOfRange,
    StudioReviewIdempotencyConflict,
    StudioReviewNotEligible,
    StudioReviewPersistenceError,
    StudioReviewRevisionConflict,
)
from thoth_control_plane.domain.models import ActorSnapshot
from thoth_control_plane.domain.studio_review import CreateComment, CreateDecision
from thoth_control_plane.infrastructure import studio_review_repository
from thoth_control_plane.infrastructure.editor_database import advisory_xact_lock, editor_sessions
from thoth_control_plane.infrastructure.editor_models import (
    EditDocumentRevisionRow,
    StudioReviewEventRow,
)
from thoth_control_plane.infrastructure.studio_review_repository import (
    PostgresStudioReviewRepository,
)

PROJECT = "project_001"
DOCUMENT = "edoc_abc123"
ACTOR = ActorSnapshot(actor_id="user_owner", actor_type="user", display_name="Owner")
START = datetime(2026, 9, 24, 9, 0, tzinfo=UTC)


@pytest.fixture(scope="module")
def migrated() -> None:
    reset_schema()


@pytest.fixture
def reviews(migrated: None) -> PostgresStudioReviewRepository:
    empty_tables()
    return PostgresStudioReviewRepository(DATABASE_URL)


def save_revision(
    revision: int, payload: dict[str, Any] | None = None, *, project_id: str = PROJECT
) -> None:
    document = payload or document_v2_payload()
    with editor_sessions(DATABASE_URL).begin() as session:
        session.add(
            EditDocumentRevisionRow(
                project_id=project_id,
                document_id=DOCUMENT,
                revision=revision,
                document_json={**document, "revision": revision},
            )
        )


def comment_request(**overrides: object) -> CreateComment:
    payload: dict[str, object] = {
        "base_revision": 3,
        "operation_id": "op_review_1",
        "text": "Check title",
        "frame": 29,
    }
    return CreateComment.model_validate(payload | overrides)


def decision_request(**overrides: object) -> CreateDecision:
    payload: dict[str, object] = {
        "base_revision": 3,
        "operation_id": "op_decide_1",
        "decision": "approved",
    }
    return CreateDecision.model_validate(payload | overrides)


def stored_events() -> int:
    with editor_sessions(DATABASE_URL)() as session:
        return session.scalar(select(func.count()).select_from(StudioReviewEventRow)) or 0


def seed_event(event_id: str, minutes: int, *, kind: str = "comment", revision: int = 3) -> None:
    comment = kind == "comment"
    with editor_sessions(DATABASE_URL).begin() as session:
        session.add(
            StudioReviewEventRow(
                event_id=event_id,
                project_id=PROJECT,
                document_id=DOCUMENT,
                revision=revision,
                operation_id=f"op_{event_id}",
                request_hash="0" * 64,
                event_kind=kind,
                actor_id="user_owner",
                actor_type="user",
                actor_display_name="Owner",
                comment_text="Check title" if comment else None,
                frame=None,
                decision=None if comment else "approved",
                reason=None,
                created_at=START + timedelta(minutes=minutes),
            )
        )


@needs_postgres
async def test_a_comment_lands_on_the_latest_saved_revision_with_a_database_stamp(
    reviews: PostgresStudioReviewRepository,
) -> None:
    save_revision(3)

    comment = await reviews.create_comment(
        project_id=PROJECT, document_id=DOCUMENT, request=comment_request(), actor=ACTOR
    )

    assert comment.document_revision == 3
    assert comment.actor == ACTOR
    assert comment.frame == 29
    assert comment.created_at.tzinfo is not None
    assert stored_events() == 1


@needs_postgres
async def test_a_review_write_waits_for_the_editor_document_lock(
    reviews: PostgresStudioReviewRepository,
) -> None:
    save_revision(3)
    holder = editor_sessions(DATABASE_URL)()
    holder.begin()
    # The key every editor save takes for this document.
    advisory_xact_lock(holder, PROJECT, DOCUMENT)
    try:
        pending = asyncio.ensure_future(
            reviews.create_comment(
                project_id=PROJECT, document_id=DOCUMENT, request=comment_request(), actor=ACTOR
            )
        )
        await asyncio.sleep(0.5)
        assert not pending.done()
    finally:
        holder.rollback()
        holder.close()

    comment = await asyncio.wait_for(pending, timeout=10)
    assert comment.document_revision == 3


@needs_postgres
async def test_a_replay_returns_the_original_record_even_after_a_newer_save(
    reviews: PostgresStudioReviewRepository,
) -> None:
    save_revision(3)
    first = await reviews.create_comment(
        project_id=PROJECT, document_id=DOCUMENT, request=comment_request(), actor=ACTOR
    )
    save_revision(4)

    replayed = await reviews.create_comment(
        project_id=PROJECT, document_id=DOCUMENT, request=comment_request(), actor=ACTOR
    )

    assert replayed == first
    assert stored_events() == 1


@needs_postgres
@pytest.mark.parametrize(
    "reuse",
    [
        lambda repo: repo.create_comment(
            project_id=PROJECT,
            document_id=DOCUMENT,
            request=comment_request(text="Different words"),
            actor=ACTOR,
        ),
        lambda repo: repo.create_comment(
            project_id=PROJECT,
            document_id=DOCUMENT,
            request=comment_request(frame=None),
            actor=ACTOR,
        ),
        lambda repo: repo.create_decision(
            project_id=PROJECT,
            document_id=DOCUMENT,
            request=decision_request(operation_id="op_review_1"),
            actor=ACTOR,
        ),
    ],
)
async def test_reusing_an_operation_id_for_another_body_or_kind_conflicts(
    reviews: PostgresStudioReviewRepository, reuse: Any
) -> None:
    save_revision(3)
    await reviews.create_comment(
        project_id=PROJECT, document_id=DOCUMENT, request=comment_request(), actor=ACTOR
    )

    with pytest.raises(StudioReviewIdempotencyConflict):
        await reuse(reviews)
    assert stored_events() == 1


@needs_postgres
async def test_a_stale_base_revision_conflicts_with_the_latest_revision(
    reviews: PostgresStudioReviewRepository,
) -> None:
    save_revision(3)
    save_revision(4)

    with pytest.raises(StudioReviewRevisionConflict) as conflict:
        await reviews.create_decision(
            project_id=PROJECT, document_id=DOCUMENT, request=decision_request(), actor=ACTOR
        )
    assert conflict.value.latest_revision == 4
    assert stored_events() == 0


@needs_postgres
async def test_a_document_the_project_does_not_own_is_not_found(
    reviews: PostgresStudioReviewRepository,
) -> None:
    save_revision(3)

    with pytest.raises(StudioReviewDocumentNotFound):
        await reviews.create_comment(
            project_id="project_other", document_id=DOCUMENT, request=comment_request(), actor=ACTOR
        )
    assert stored_events() == 0


@needs_postgres
async def test_a_frame_must_fall_inside_the_saved_canvas(
    reviews: PostgresStudioReviewRepository,
) -> None:
    save_revision(3)

    with pytest.raises(StudioReviewFrameOutOfRange):
        await reviews.create_comment(
            project_id=PROJECT,
            document_id=DOCUMENT,
            request=comment_request(frame=300),
            actor=ACTOR,
        )
    assert stored_events() == 0

    comment = await reviews.create_comment(
        project_id=PROJECT,
        document_id=DOCUMENT,
        request=comment_request(operation_id="op_review_2", frame=299),
        actor=ACTOR,
    )
    assert comment.frame == 299


@needs_postgres
async def test_approval_is_refused_on_a_revision_with_blocking_issues(
    reviews: PostgresStudioReviewRepository,
) -> None:
    gapped = document_v2_payload()
    clip_by_id(gapped, "clip_main")["from_frame"] = 30
    clip_by_id(gapped, "clip_main")["duration_in_frames"] = 270
    save_revision(3, gapped)

    with pytest.raises(StudioReviewNotEligible) as blocked:
        await reviews.create_decision(
            project_id=PROJECT, document_id=DOCUMENT, request=decision_request(), actor=ACTOR
        )
    assert blocked.value.issues == ("main_track_gap",)
    assert stored_events() == 0

    decision = await reviews.create_decision(
        project_id=PROJECT,
        document_id=DOCUMENT,
        request=decision_request(
            operation_id="op_decide_2", decision="changes_requested", reason="Close the gap"
        ),
        actor=ACTOR,
    )
    assert decision.decision == "changes_requested"
    assert decision.reason == "Close the gap"


@needs_postgres
async def test_comments_list_oldest_first_with_a_keyset_cursor(
    reviews: PostgresStudioReviewRepository,
) -> None:
    save_revision(3)
    seed_event("rev_a", 0)
    seed_event("rev_b", 0)
    seed_event("rev_c", 5)
    seed_event("rev_decision", 1, kind="decision")

    first = await reviews.list_comments(
        project_id=PROJECT, document_id=DOCUMENT, limit=2, cursor=None
    )
    second = await reviews.list_comments(
        project_id=PROJECT, document_id=DOCUMENT, limit=2, cursor=first.next_cursor
    )

    assert [comment.comment_id for comment in first.comments] == ["rev_a", "rev_b"]
    assert first.next_cursor is not None
    assert [comment.comment_id for comment in second.comments] == ["rev_c"]
    assert second.next_cursor is None


@needs_postgres
async def test_decisions_list_newest_first_and_keep_historical_approvals(
    reviews: PostgresStudioReviewRepository,
) -> None:
    save_revision(3)
    save_revision(4)
    seed_event("rev_old", 0, kind="decision", revision=3)
    seed_event("rev_new", 5, kind="decision", revision=4)
    seed_event("rev_comment", 9)

    page = await reviews.list_decisions(
        project_id=PROJECT, document_id=DOCUMENT, limit=50, cursor=None
    )

    assert [(item.decision_id, item.document_revision) for item in page.decisions] == [
        ("rev_new", 4),
        ("rev_old", 3),
    ]
    assert page.decisions[1].decision == "approved"
    assert page.next_cursor is None


@pytest.mark.parametrize(
    ("limit", "page_cursor"),
    [(0, None), (51, None), (10, "not a cursor!"), (10, "bm90LWEtY3Vyc29y"), (10, "")],
)
async def test_an_invalid_limit_or_cursor_is_refused_before_any_query(
    limit: int, page_cursor: str | None
) -> None:
    # An unreachable database: a page check that queried first would fail differently.
    unreachable = PostgresStudioReviewRepository("postgresql://user:secret@127.0.0.1:1/editor")

    with pytest.raises(InvalidStudioReviewPage):
        await unreachable.list_comments(
            project_id=PROJECT, document_id=DOCUMENT, limit=limit, cursor=page_cursor
        )


async def test_a_failure_is_the_safe_error_and_leaks_nothing() -> None:
    unreachable = PostgresStudioReviewRepository("postgresql://user:secret@127.0.0.1:1/editor")

    with pytest.raises(StudioReviewPersistenceError) as failure:
        await unreachable.create_comment(
            project_id=PROJECT, document_id=DOCUMENT, request=comment_request(), actor=ACTOR
        )
    assert "secret" not in str(failure.value)


def test_the_review_store_only_ever_inserts_and_reads() -> None:
    # A row lock (`with_for_update`, `FOR UPDATE`) reads; it never changes a row.
    source = (
        inspect.getsource(studio_review_repository)
        .replace("with_for_update(", "")
        .replace("FOR UPDATE", "")
    )

    for writer in ("update(", "delete(", ".delete", "UPDATE ", "DELETE "):
        assert writer not in source
