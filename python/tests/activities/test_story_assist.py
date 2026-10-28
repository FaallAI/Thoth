"""The Story Assist activity: one provider call inside the worker, safe codes out."""

from __future__ import annotations

from typing import Any

import pytest

from tests.test_metering import Sink
from thoth_control_plane import metering
from thoth_control_plane.activities.story_assist import StoryAssistActivity
from thoth_control_plane.application.prompt_proposal_ports import ProviderTimeout
from thoth_control_plane.domain.story_assist import StoryAssistInput

pytestmark = pytest.mark.asyncio

INPUT = StoryAssistInput(project_id="p1", provider_id="novita", model_id="m1", system="s", user="u")


class Provider:
    def __init__(self, answer: Any = None, error: Exception | None = None) -> None:
        self.answer = answer
        self.error = error
        self.calls: list[dict[str, str]] = []

    async def complete_json(self, **request: str) -> Any:
        self.calls.append(request)
        await metering.record_call(request["model_id"], tokens_in=3)
        if self.error:
            raise self.error
        return self.answer


async def test_activity_returns_the_parsed_proposal() -> None:
    provider = Provider({"title": "Shorter hook", "reason": "31 characters", "text": "Asap lagi"})

    result = await StoryAssistActivity(provider=provider).run(INPUT)

    assert (result.code, result.title, result.reason, result.text) == (
        None,
        "Shorter hook",
        "31 characters",
        "Asap lagi",
    )
    assert provider.calls == [
        {"provider_id": "novita", "model_id": "m1", "system": "s", "user": "u"}
    ]


async def test_activity_maps_provider_failures_to_safe_codes() -> None:
    result = await StoryAssistActivity(provider=Provider(error=ProviderTimeout())).run(INPUT)

    assert (result.code, result.text) == ("provider_timeout", "")


@pytest.mark.parametrize(
    "answer", [{"title": "t", "reason": "r"}, {"title": "t", "reason": "r", "text": 5}, ["text"]]
)
async def test_activity_rejects_a_malformed_answer(answer: Any) -> None:
    result = await StoryAssistActivity(provider=Provider(answer)).run(INPUT)

    assert result.code == "invalid_provider_output"


async def test_activity_meters_the_call_for_the_project_workspace() -> None:
    sink = Sink(projects={"p1": "ws_9"})
    metering.install(sink)
    try:
        await StoryAssistActivity(
            provider=Provider({"title": "t", "reason": "r", "text": "x"})
        ).run(INPUT)
    finally:
        metering.install(None)

    assert {(event.workspace_id, event.project_id, event.key) for event in sink.events} == {
        ("ws_9", "p1", "m1")
    }
