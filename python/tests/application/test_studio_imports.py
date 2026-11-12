"""Tests for creating, replaying, and listing Studio drafts from a projected source."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from pydantic import ValidationError

from tests.domain.test_studio_imports import item, projection_payload
from thoth_control_plane.application.edit_documents import EditorUnavailable
from thoth_control_plane.application.ports import (
    StudioImportConflict,
    StudioImportSourceMismatch,
)
from thoth_control_plane.application.studio_imports import (
    StudioImportService,
    build_studio_draft,
)
from thoth_control_plane.domain.edit_document_v2 import EditDocumentV2
from thoth_control_plane.domain.studio_imports import (
    CreateStudioImport,
    StudioDraft,
    StudioImportInventory,
    StudioImportItem,
    StudioSourceProjection,
    inventory,
    source_key,
)

NOW = datetime(2026, 9, 25, 9, 0, tzinfo=UTC)
PROJECT = "project_001"


class MemoryStudioImports:
    """In-memory stand-in that keeps the port's replay and isolation semantics."""

    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []
        self.writes = 0

    async def create_draft(
        self,
        *,
        project_id: str,
        source_key: str,
        idempotency_key: str,
        document: EditDocumentV2,
        inventory: list[StudioImportItem],
        source_workflow_id: str | None = None,
    ) -> StudioDraft:
        for row in self.rows:
            if (row["project_id"], row["idempotency_key"]) == (project_id, idempotency_key):
                if row["draft"].source_key != source_key:
                    raise StudioImportConflict()
                return row["draft"]
        self.writes += 1
        draft = StudioDraft(
            document_id=document.document_id,
            source_key=source_key,
            revision=document.revision,
            created_at=NOW + timedelta(minutes=len(self.rows)),
        )
        self.rows.append(
            {
                "project_id": project_id,
                "idempotency_key": idempotency_key,
                "draft": draft,
                "document": document,
                "inventory": inventory,
                "source_workflow_id": source_workflow_id,
            }
        )
        return draft

    async def list_drafts(
        self, *, project_id: str, source_key: str, limit: int
    ) -> list[StudioDraft]:
        drafts = [
            row["draft"]
            for row in self.rows
            if row["project_id"] == project_id and row["draft"].source_key == source_key
        ]
        return sorted(drafts, key=lambda draft: draft.created_at, reverse=True)[:limit]

    async def count_drafts(self, project_id: str, source_key: str) -> int:
        return len(await self.list_drafts(project_id=project_id, source_key=source_key, limit=999))

    async def get_inventory(
        self, *, project_id: str, document_id: str
    ) -> StudioImportInventory | None:
        for row in self.rows:
            if (row["project_id"], row["draft"].document_id) == (project_id, document_id):
                return StudioImportInventory(
                    document_id=document_id,
                    source_key=row["draft"].source_key,
                    revision=row["draft"].revision,
                    items=row["inventory"],
                    source_workflow_id=row.get("source_workflow_id"),
                )
        return None


def create_request(payload: dict[str, Any] | None = None) -> CreateStudioImport:
    projection = StudioSourceProjection.model_validate(payload or projection_payload())
    return CreateStudioImport(source=projection, source_key=source_key(projection))


@pytest.mark.asyncio
async def test_inspect_lists_drafts_for_the_source_without_writing() -> None:
    repository = MemoryStudioImports()
    service = StudioImportService(repository)
    projection = create_request().source

    first = await service.inspect(PROJECT, projection)
    assert first.drafts == []
    assert repository.writes == 0

    created = await service.create(PROJECT, create_request(), "open-1")
    again = await service.inspect(PROJECT, projection)
    assert [draft.document_id for draft in again.drafts] == [created.document_id]
    assert again.drafts[0].revision == 1
    assert repository.writes == 1


@pytest.mark.asyncio
async def test_replaying_create_returns_the_same_draft() -> None:
    repository = MemoryStudioImports()
    service = StudioImportService(repository)
    request = create_request()

    first = await service.create(PROJECT, request, "open-1")
    replay = await service.create(PROJECT, request, "open-1")

    assert replay.document_id == first.document_id
    assert await repository.count_drafts(PROJECT, request.source_key) == 1


@pytest.mark.asyncio
async def test_an_explicit_second_create_makes_a_second_draft_listed_newest_first() -> None:
    repository = MemoryStudioImports()
    service = StudioImportService(repository)
    request = create_request()

    first = await service.create(PROJECT, request, "open-1")
    second = await service.create(PROJECT, request, "open-2")
    listing = await service.list_drafts(PROJECT, request.source_key)

    assert second.document_id != first.document_id
    assert [draft.document_id for draft in listing.drafts] == [
        second.document_id,
        first.document_id,
    ]
    assert listing.more_drafts is False


@pytest.mark.asyncio
async def test_drafts_of_another_project_are_never_listed() -> None:
    repository = MemoryStudioImports()
    service = StudioImportService(repository)
    request = create_request()
    await service.create("project_002", request, "open-1")

    assert (await service.inspect(PROJECT, request.source)).drafts == []


@pytest.mark.asyncio
async def test_a_source_key_the_server_does_not_derive_is_refused_before_any_write() -> None:
    repository = MemoryStudioImports()
    service = StudioImportService(repository)
    stale = create_request().model_copy(update={"source_key": "0" * 64})

    with pytest.raises(StudioImportSourceMismatch):
        await service.create(PROJECT, stale, "open-1")
    assert repository.writes == 0


@pytest.mark.asyncio
async def test_create_refuses_an_unsafe_idempotency_key() -> None:
    with pytest.raises(ValidationError):
        await StudioImportService(MemoryStudioImports()).create(
            PROJECT, create_request(), "C:\\Users\\key"
        )


@pytest.mark.asyncio
async def test_every_operation_is_unavailable_without_storage() -> None:
    service = StudioImportService(None)
    with pytest.raises(EditorUnavailable):
        await service.inspect(PROJECT, create_request().source)
    with pytest.raises(EditorUnavailable):
        await service.create(PROJECT, create_request(), "open-1")


def test_the_draft_has_one_text_scene_per_ordered_source_item() -> None:
    document = build_studio_draft(PROJECT, "edoc_first", create_request().source)

    assert isinstance(document, EditDocumentV2)
    assert document.revision == 1
    assert [scene.scene_id for scene in document.scenes] == [
        f"scene_{index:03d}" for index in range(1, 7)
    ]
    headings = [clip.heading for clip in document.clips]
    assert headings == [
        "main 0",
        "footage 0",
        "footage 1",
        "footage 2",
        "footage 3",
        "viewer_one",
    ]
    assert document.clips[0].body == ""
    assert document.canvas.duration_in_frames == 6 * 150
    serialized = document.model_dump_json()
    assert "example.com" not in serialized
    assert "source_url" not in serialized


def test_a_new_drafts_headings_start_at_the_top_and_quoted_text_stays_in_the_middle() -> None:
    # The first narrated draft of 2026-11-05: a mid-frame title ran over the comment card.
    document = build_studio_draft(PROJECT, "edoc_first", create_request().source)

    assert [clip.style_slot for clip in document.clips] == [
        "title_top",
        "title_top",
        "title_top",
        "title_top",
        "title_top",
        "source",
    ]


def test_an_account_credit_goes_to_the_credit_corner_and_a_quote_stays_in_the_middle() -> None:
    # A source's @account read as a big mid-frame title (operator, 2026-11-12).
    payload = projection_payload()
    payload["items"] = [
        item("main", 0, text="Main caption", platform="tiktok"),
        item("creator_photo", 0, title="Photo 1", text=None, media_kind="image"),
        item("footage", 0, title="@kompastv"),
        item("comment", 0, title="@viewer", text="A quote", media_kind="image"),
    ]
    document = build_studio_draft(PROJECT, "edoc_first", create_request(payload).source)

    assert [(clip.heading, clip.style_slot) for clip in document.clips] == [
        ("main 0", "title_top"),
        ("Photo 1", "source"),
        ("@kompastv", "credit"),
        ("@viewer", "source"),
    ]


def _with_post_and_profile() -> dict[str, Any]:
    payload = projection_payload()
    payload["items"] = [
        item("main", 0, text="Main caption", platform="tiktok"),
        item(
            "post_card",
            0,
            title="@cnnindonesia",
            text=None,
            media_kind="image",
            reading_seconds=3.0,
        ),
        item("profile_page", 0, title="@cnnindonesia", text=None, media_kind="image"),
        item("footage", 0, title="@kompastv"),
    ]
    return payload


def test_the_post_and_profile_page_stay_in_materials_off_the_timeline() -> None:
    # Operator, 2026-11-12: "post, dan profile page tuh sebenarnya tidak perlu masuk ke content".
    source = create_request(_with_post_and_profile()).source
    document = build_studio_draft(PROJECT, "edoc_first", source)
    assert [clip.source_role for clip in document.clips if clip.clip_id != "clip_credit"] == [
        "main",
        "footage",
    ]
    listed = {entry.item_id: entry for entry in inventory(source)}
    for item_id in ("post_card_000", "profile_page_000"):
        assert listed[item_id].scene_id is None
        assert listed[item_id].disposition == "excluded"


def test_the_main_videos_account_credit_rides_over_the_main_scene() -> None:
    # The credit kept its corner when the profile page left the timeline (operator, 2026-11-12).
    document = build_studio_draft(
        PROJECT, "edoc_first", create_request(_with_post_and_profile()).source
    )
    title, credit = document.clips[0], document.clips[1]
    assert (credit.heading, credit.style_slot, credit.source_role) == (
        "@cnnindonesia",
        "credit",
        "main",
    )
    assert (credit.from_frame, credit.duration_in_frames, credit.scene_id) == (
        title.from_frame,
        title.duration_in_frames,
        title.scene_id,
    )


def test_each_text_scene_carries_its_items_role_so_it_has_a_story_beat() -> None:
    # Without it a quoted comment had no beat: narration crammed it over the footage titles.
    document = build_studio_draft(PROJECT, "edoc_first", create_request().source)

    assert [clip.source_role for clip in document.clips] == [
        "main",
        "footage",
        "footage",
        "footage",
        "footage",
        "comment",
    ]


def test_main_and_footage_scenes_show_their_heading_only() -> None:
    # A main's text repeats its title; a footage description is for scoring, not the screen.
    payload = projection_payload()
    payload["items"][2]["text"] = "A flooded street."
    document = build_studio_draft(PROJECT, "edoc_first", create_request(payload).source)

    assert [(clip.heading, clip.body) for clip in document.clips[:2]] == [
        ("main 0", ""),
        ("footage 0", ""),
    ]
    assert document.clips[-1].body == "First"


def test_the_draft_stops_at_the_scene_limit_and_titles_untitled_items() -> None:
    payload = projection_payload()
    payload["items"] = [
        item("main", 0, title=None),
        *(item("footage", index, title=None) for index in range(120)),
    ]
    document = build_studio_draft(PROJECT, "edoc_first", create_request(payload).source)

    assert len(document.scenes) == 100
    assert document.clips[0].heading == "Untitled video"
    assert document.clips[1].heading == "Footage 1"


async def test_a_keyed_draft_lives_under_the_given_key_not_the_projection_hash() -> None:
    repository = MemoryStudioImports()
    service = StudioImportService(repository)
    projection = create_request().source
    key = "f" * 64

    draft = await service.create_keyed(PROJECT, key, projection, "wf-open-1")
    again = await service.create_keyed(PROJECT, key, projection, "wf-open-1")

    assert (draft.source_key, again.document_id) == (key, draft.document_id)
    inspection = await service.inspect_keyed(PROJECT, key, projection)
    assert inspection.source_key == key
    assert [found.document_id for found in inspection.drafts] == [draft.document_id]
    assert (await service.inspect(PROJECT, projection)).drafts == []


async def test_a_keyed_draft_refuses_an_unsafe_idempotency_key() -> None:
    with pytest.raises(ValidationError):
        await StudioImportService(MemoryStudioImports()).create_keyed(
            PROJECT, "f" * 64, create_request().source, "C:\\Users\\key"
        )
