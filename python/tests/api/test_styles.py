"""Applying a style through the API (spec 2026-11-10, 6): one revision, then a narration."""

from __future__ import annotations

import httpx

from tests.api.test_narrations import AUTH, DOC, Gateway, Store, build, code
from thoth_control_plane.domain.narration import NarrationState

STYLE = f"{DOC}/style"
UNDO = f"{DOC}/style/undo"


def waiting(status: str) -> NarrationState:
    return NarrationState(
        document_id="edoc_abc123", workflow_id="narration/edoc_abc123/1", status=status
    )


async def apply(api: httpx.AsyncClient, template_id: str = "style_a", base: int = 1):  # type: ignore[no-untyped-def]
    return await api.post(
        STYLE, json={"template_id": template_id, "base_revision": base}, headers=AUTH
    )


async def test_the_built_in_styles_are_listed() -> None:
    async with build(Store(), Gateway()) as api:
        listed = await api.get("/api/v1/projects/project_001/styles", headers=AUTH)
    assert listed.status_code == 200
    assert [(s["template_id"], s["name"]) for s in listed.json()] == [
        ("style_a", "Style A"),
        ("style_b", "Style B"),
    ]


async def test_apply_makes_one_revision_and_starts_a_narration() -> None:
    store, gateway = Store(), Gateway()
    async with build(store, gateway) as api:
        answer = await apply(api)
    assert answer.status_code == 200
    body = answer.json()
    assert (body["document"]["revision"], body["previous_revision"]) == (2, 1)
    assert body["document"]["style"] == {"template_id": "style_a", "revision": 1}
    assert body["narration_refused"] is None
    assert len(gateway.started) == 1


async def test_apply_while_narration_waits_is_refused_unchanged() -> None:
    store, gateway = Store(), Gateway()
    store.state = waiting("awaiting_approval")
    async with build(store, gateway) as api:
        answer = await apply(api)
        latest = await api.get(DOC, headers=AUTH)
    assert (answer.status_code, code(answer)) == (409, "narration_in_progress")
    assert latest.json()["revision"] == 1
    assert gateway.started == []


async def test_apply_without_a_model_keeps_the_look_and_says_why() -> None:
    store, gateway = Store(), Gateway()
    async with build(store, gateway, configured=False) as api:
        answer = await apply(api)
    assert answer.status_code == 200
    assert answer.json()["document"]["revision"] == 2
    assert answer.json()["narration_refused"] == "prompt_not_configured"


async def test_unknown_template_is_404() -> None:
    async with build(Store(), Gateway()) as api:
        answer = await apply(api, "style_nobody")
    assert answer.status_code == 404


async def test_stale_base_revision_is_409() -> None:
    async with build(Store(), Gateway()) as api:
        answer = await apply(api, base=7)
    assert answer.status_code == 409


async def test_undo_stops_the_styles_narration_and_restores_the_draft() -> None:
    # The restore route refuses while a narration runs, so a style has its own undo.
    store, gateway = Store(), Gateway()
    async with build(store, gateway) as api:
        await apply(api)
        assert store.state is not None and store.state.status == "transcribing"
        undone = await api.post(UNDO, json={"base_revision": 2, "revision": 1}, headers=AUTH)
    assert undone.status_code == 200
    assert undone.json()["revision"] == 3
    assert "style" not in undone.json()
    assert gateway.cancelled == [store.state.workflow_id]


async def test_undo_waits_once_the_voice_is_being_made() -> None:
    store, gateway = Store(), Gateway()
    async with build(store, gateway) as api:
        await apply(api)
        store.state = waiting("voicing")
        undone = await api.post(UNDO, json={"base_revision": 2, "revision": 1}, headers=AUTH)
    assert (undone.status_code, code(undone)) == (409, "narration_in_progress")
    assert gateway.cancelled == []


async def test_the_cut_preview_waits_for_a_script() -> None:
    async with build(Store(), Gateway()) as api:
        answer = await api.get(f"{DOC}/narration/preview", headers=AUTH)
    assert (answer.status_code, code(answer)) == (409, "no_script")


async def test_the_cut_preview_is_computed_and_never_saved() -> None:
    from thoth_control_plane.domain.narration import NarrationScript

    store, gateway = Store(), Gateway()
    async with build(store, gateway) as api:
        await apply(api, "style_b")
        script = NarrationScript.model_validate(
            {"beats": [{"beat": "main", "text": "Satu dua tiga. Empat lima."}], "sfx_cues": []}
        )
        store.state = waiting("awaiting_approval").model_copy(update={"script": script})
        answer = await api.get(f"{DOC}/narration/preview", headers=AUTH)
        latest = await api.get(DOC, headers=AUTH)
    assert answer.status_code == 200
    assert answer.json()["style"]["template_id"] == "style_b"
    assert latest.json()["revision"] == 2
