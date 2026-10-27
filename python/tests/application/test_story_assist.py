"""Story Assist (spec 2026-10-27, section 7): one text proposal, applied only by the editor."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from thoth_control_plane.application.ports import (
    EditDocumentRevisionConflict,
    PromptBindingNotFound,
)
from thoth_control_plane.application.story_assist import (
    StoryAssistInvalidOutput,
    StoryAssistNotConfigured,
    StoryAssistNoText,
    StoryAssistService,
    StoryAssistUnavailable,
)
from thoth_control_plane.domain.edit_document_v2 import EditDocumentV2
from thoth_control_plane.domain.prompts import PROMPT_STARTERS
from thoth_control_plane.domain.story_assist import (
    StoryAssistInput,
    StoryAssistOutput,
    StoryAssistRequest,
)

pytestmark = pytest.mark.asyncio

CASES = json.loads(
    (Path(__file__).parents[1] / "fixtures" / "story_operation_cases.json").read_text("utf-8")
)


def document() -> EditDocumentV2:
    payload = json.loads(json.dumps(CASES["base"]))
    payload["clips"] += [
        {
            "kind": "text",
            "clip_id": "clip_hook",
            "track_id": "track_overlay",
            "scene_id": None,
            "from_frame": 0,
            "duration_in_frames": 120,
            "ownership": "user_edited",
            "heading": "Kabut asap",
            "body": "",
            "style_slot": "title",
            "source_role": "hook",
        },
        {
            "kind": "caption",
            "clip_id": "clip_caption",
            "track_id": "track_caption",
            "scene_id": None,
            "from_frame": 0,
            "duration_in_frames": 90,
            "ownership": "ai_managed",
            "style_slot": "caption_default",
            "cues": [{"from_frame": 0, "duration_in_frames": 90, "text": "old line"}],
        },
    ]
    for track in payload["tracks"]:
        if track["track_id"] == "track_overlay":
            track["clip_ids"].append("clip_hook")
        if track["track_id"] == "track_caption":
            track["clip_ids"].append("clip_caption")
    return EditDocumentV2.model_validate(payload)


class Documents:
    async def get_latest(self, project_id: str, document_id: str) -> EditDocumentV2:
        return document()


class Preferences:
    def __init__(self, configured: bool = True) -> None:
        self.configured = configured

    async def get_preference(self, project_id: str, stage_id: str) -> Any:
        assert stage_id == "story_assist"
        if not self.configured:
            return None
        return type("Preference", (), {"provider_id": "novita", "model_id": "m1"})()


class Prompts:
    def __init__(self, saved: str | None = None) -> None:
        self.saved = saved

    async def get_resolved_prompt(self, project_id: str, stage_id: str) -> Any:
        if self.saved is None:
            raise PromptBindingNotFound()
        return type("Resolved", (), {"visible_text": self.saved})()


class Gateway:
    def __init__(self, output: StoryAssistOutput) -> None:
        self.output = output
        self.inputs: list[StoryAssistInput] = []

    async def complete(self, request: StoryAssistInput) -> StoryAssistOutput:
        self.inputs.append(request)
        return self.output


async def context(project_id: str, document_id: str) -> tuple[str, str] | None:
    return ("Kabut asap Kalteng makin parah", "Warga Palangka Raya mengeluh " + "x" * 600)


def service(output: StoryAssistOutput, **overrides: Any) -> tuple[StoryAssistService, Gateway]:
    gateway = Gateway(output)
    built = StoryAssistService(
        documents=overrides.get("documents", Documents()),
        preferences=overrides.get("preferences", Preferences()),
        prompts=overrides.get("prompts", Prompts()),
        context=overrides.get("context", context),
        gateway=gateway,
    )
    return built, gateway


def answer(text: str) -> StoryAssistOutput:
    return StoryAssistOutput(
        title="Shorter hook", reason="Readable in the 4-second hook", text=text
    )


def ask(*clip_ids: str, beat: str = "hook", revision: int = 1) -> StoryAssistRequest:
    return StoryAssistRequest(base_revision=revision, beat=beat, clip_ids=list(clip_ids))  # type: ignore[arg-type]


async def test_assist_builds_replace_text() -> None:
    assist, gateway = service(answer("Asap Kalteng makin parah"))

    proposal = await assist.propose("project_001", "edoc_abc123", ask("clip_hook"))

    assert proposal.proposal_id.startswith("assist_")
    assert (proposal.title, proposal.reason) == ("Shorter hook", "Readable in the 4-second hook")
    [operation] = proposal.operations
    assert operation.model_dump(exclude={"operation_id"}) == {
        "kind": "replace_text",
        "clip_id": "clip_hook",
        "field": "heading",
        "value": "Asap Kalteng makin parah",
    }
    [sent] = gateway.inputs
    assert (sent.project_id, sent.provider_id, sent.model_id) == ("project_001", "novita", "m1")
    assert sent.system == PROMPT_STARTERS["story_assist"].body
    assert "Beat: hook" in sent.user and "Kabut asap" in sent.user
    assert "Kabut asap Kalteng makin parah" in sent.user  # the run title
    assert "at most 60 characters" in sent.user  # 4 s at 15 chars/s
    assert "x" * 501 not in sent.user  # the description is cut to 500 characters


async def test_assist_caption_cue() -> None:
    assist, _ = service(answer("Asap tebal sejak pagi"))

    proposal = await assist.propose("project_001", "edoc_abc123", ask("clip_caption", beat="main"))

    [operation] = proposal.operations
    assert operation.model_dump(exclude={"operation_id"}) == {
        "kind": "set_caption_cue_text",
        "clip_id": "clip_caption",
        "cue_index": 0,
        "text": "Asap tebal sejak pagi",
    }


async def test_assist_uses_the_saved_prompt() -> None:
    assist, gateway = service(answer("x"), prompts=Prompts(saved="Project's own assist prompt"))

    await assist.propose("project_001", "edoc_abc123", ask("clip_hook"))

    assert gateway.inputs[0].system == "Project's own assist prompt"


async def test_assist_rejects_overlong_text() -> None:
    assist, _ = service(answer("a" * 61))

    with pytest.raises(StoryAssistInvalidOutput):
        await assist.propose("project_001", "edoc_abc123", ask("clip_hook"))


@pytest.mark.parametrize("text", ["", "   "])
async def test_assist_rejects_blank_text(text: str) -> None:
    assist, _ = service(answer(text))

    with pytest.raises(StoryAssistInvalidOutput):
        await assist.propose("project_001", "edoc_abc123", ask("clip_hook"))


async def test_assist_rejects_malformed_output() -> None:
    assist, _ = service(StoryAssistOutput(code="invalid_provider_output"))

    with pytest.raises(StoryAssistInvalidOutput):
        await assist.propose("project_001", "edoc_abc123", ask("clip_hook"))


async def test_assist_unavailable() -> None:
    assist, _ = service(StoryAssistOutput(code="provider_timeout"))

    with pytest.raises(StoryAssistUnavailable):
        await assist.propose("project_001", "edoc_abc123", ask("clip_hook"))


async def test_assist_not_configured() -> None:
    assist, gateway = service(answer("x"), preferences=Preferences(configured=False))

    with pytest.raises(StoryAssistNotConfigured):
        await assist.propose("project_001", "edoc_abc123", ask("clip_hook"))
    assert gateway.inputs == []


async def test_assist_revision_conflict() -> None:
    assist, gateway = service(answer("x"))

    with pytest.raises(EditDocumentRevisionConflict):
        await assist.propose("project_001", "edoc_abc123", ask("clip_hook", revision=9))
    assert gateway.inputs == []


async def test_assist_needs_a_text_clip() -> None:
    assist, gateway = service(answer("x"))

    with pytest.raises(StoryAssistNoText):
        await assist.propose(
            "project_001", "edoc_abc123", ask("clip_comment_card_000", beat="reactions")
        )
    assert gateway.inputs == []


async def test_assist_without_a_gateway_is_unavailable() -> None:
    assist = StoryAssistService(
        documents=Documents(),
        preferences=Preferences(),
        prompts=Prompts(),
        context=context,
        gateway=None,
    )

    with pytest.raises(StoryAssistUnavailable):
        await assist.propose("project_001", "edoc_abc123", ask("clip_hook"))


async def test_story_assist_stage_listed() -> None:
    from thoth_control_plane.domain.prompts import PROMPT_STAGES

    assert "story_assist" in {stage.stage_id for stage in PROMPT_STAGES}
    assert PROMPT_STARTERS["story_assist"].language == "en-US"
