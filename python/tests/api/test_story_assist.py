"""The Story Assist route: one proposal, or a code the editor can explain (spec 2026-10-27, 7)."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from tests.api.open_projects import OPEN_PROJECTS
from tests.api.test_edit_documents import MemoryEditDocumentRepository
from tests.application.test_story_assist import (
    Documents,
    Gateway,
    Preferences,
    Prompts,
    answer,
    context,
)
from thoth_control_plane.api import create_app
from thoth_control_plane.application.story_assist import StoryAssistService
from thoth_control_plane.config import Settings
from thoth_control_plane.domain.story_assist import StoryAssistOutput

pytestmark = pytest.mark.asyncio
AUTH = {"Authorization": "Bearer test-key"}
PATH = "/api/v1/projects/project_001/edit-documents/edoc_abc123/assist"
BODY = {"base_revision": 1, "beat": "hook", "clip_ids": ["clip_hook"]}


def client(output: StoryAssistOutput, **overrides: Any) -> httpx.AsyncClient:
    app = create_app(
        Settings(THOTH_CONTROL_PLANE_API_KEY="test-key"),
        None,
        MemoryEditDocumentRepository(),
        project_store=OPEN_PROJECTS,
    )
    app.state.story_assist_service = StoryAssistService(
        documents=Documents(),
        preferences=overrides.get("preferences", Preferences()),
        prompts=Prompts(),
        context=context,
        gateway=Gateway(output),
    )
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


def code(response: httpx.Response) -> Any:
    detail = response.json().get("detail")
    return detail.get("code") if isinstance(detail, dict) else detail


async def test_assist_answers_one_proposal() -> None:
    async with client(answer("Asap Kalteng makin parah")) as api:
        response = await api.post(PATH, json=BODY, headers=AUTH)

    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "Shorter hook"
    assert [operation["kind"] for operation in body["operations"]] == ["replace_text"]


@pytest.mark.parametrize(
    ("output", "body", "status", "expected"),
    [
        (answer("a" * 61), BODY, 422, "assist_invalid_output"),
        (StoryAssistOutput(code="provider_unavailable"), BODY, 503, "assist_unavailable"),
        (answer("x"), {**BODY, "clip_ids": ["clip_comment_card_000"]}, 422, "assist_no_text"),
    ],
)
async def test_assist_refusals_carry_a_code(
    output: StoryAssistOutput, body: dict, status: int, expected: str
) -> None:
    async with client(output) as api:
        response = await api.post(PATH, json=body, headers=AUTH)

    assert (response.status_code, code(response)) == (status, expected)


async def test_assist_without_a_model_is_not_configured() -> None:
    async with client(answer("x"), preferences=Preferences(configured=False)) as api:
        response = await api.post(PATH, json=BODY, headers=AUTH)

    assert (response.status_code, code(response)) == (409, "assist_not_configured")


async def test_assist_on_an_old_revision_answers_the_latest() -> None:
    async with client(answer("x")) as api:
        response = await api.post(PATH, json={**BODY, "base_revision": 9}, headers=AUTH)

    assert response.status_code == 409
    assert response.json()["code"] == "document_revision_conflict"
    assert response.json()["latest"]["revision"] == 1
