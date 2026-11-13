"""Planner stage 1: one OpenRouter call per draft, retried, with a fallback model and clamping."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from thoth_control_plane.assembly.adapters.planner_model import (
    PhraseAnswer,
    PhraseAsk,
    PlannerModel,
    PlannerUnavailable,
)
from thoth_control_plane.assembly.planner_shots import Sheet

SHEETS = [Sheet("MAIN", ["S1", "S2"], b"jpeg-1"), Sheet("F1", ["S3", "S4"], b"jpeg-2")]
PHRASES = [PhraseAsk("P1", "main", "Rocky kena semprot!"), PhraseAsk("P2", "reactions", "Nah.")]
SHOT_IDS = {"S1", "S2", "S3", "S4"}
CARD_IDS = {"C1", "C2"}


def answer(phrases: list[dict[str, Any]], finish: str = "stop") -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [
                {"finish_reason": finish, "message": {"content": json.dumps({"phrases": phrases})}}
            ],
            "usage": {"prompt_tokens": 1000, "completion_tokens": 200},
        },
    )


GOOD = [{"id": "P1", "base": ["S1"], "overlay": [], "fit": "shows", "why": "Rocky terlihat."}]


class Recorder:
    def __init__(self, responses: list[httpx.Response]) -> None:
        self.responses = responses
        self.bodies: list[dict[str, Any]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.bodies.append(json.loads(request.content))
        assert request.headers["Authorization"] == "Bearer key"
        return self.responses.pop(0)


async def _no_sleep(_: float) -> None:
    return None


def model(recorder: Recorder, fallback: str | None = "fallback/model") -> PlannerModel:
    client = httpx.AsyncClient(transport=httpx.MockTransport(recorder))
    return PlannerModel("key", "cheap/model", fallback, client=client, sleep=_no_sleep)


async def ask(planner: PlannerModel, cards: bytes | None = b"cards") -> list[PhraseAnswer]:
    return await planner.ask(
        "SOURCES: ...", SHEETS, cards, "[main] ...", PHRASES, SHOT_IDS, CARD_IDS
    )


async def test_body_carries_the_trial_settings_and_the_images() -> None:
    recorder = Recorder([answer(GOOD)])
    await ask(model(recorder))
    body = recorder.bodies[0]
    assert body["model"] == "cheap/model"
    assert body["temperature"] == 0 and body["reasoning"] == {"effort": "low"}
    assert body["provider"] == {"data_collection": "deny"} and body["max_tokens"] == 12000
    assert body["response_format"] == {"type": "json_object"} and body["usage"] == {"include": True}
    content = body["messages"][1]["content"]
    assert sum(part["type"] == "image_url" for part in content) == len(SHEETS) + 1
    assert content[-1]["text"].endswith("P1 [main]: Rocky kena semprot!\nP2 [reactions]: Nah.")
    assert "Soundbite first" in body["messages"][0]["content"]


async def test_a_429_is_retried_then_answered() -> None:
    recorder = Recorder([httpx.Response(429), httpx.Response(429), answer(GOOD)])
    planner = model(recorder)
    assert await ask(planner) == [PhraseAnswer("P1", ["S1"], None, "Rocky terlihat.")]
    assert [b["model"] for b in recorder.bodies] == ["cheap/model"] * 3
    assert planner.model_used == "cheap/model"


async def test_truncation_moves_to_the_fallback_model() -> None:
    recorder = Recorder([answer(GOOD, finish="length"), answer(GOOD)])
    planner = model(recorder)
    await ask(planner)
    assert [b["model"] for b in recorder.bodies] == ["cheap/model", "fallback/model"]
    assert planner.model_used == "fallback/model"


async def test_both_models_failing_raises_planner_unavailable() -> None:
    recorder = Recorder([httpx.Response(429)] * 3 + [httpx.Response(500)])
    with pytest.raises(PlannerUnavailable):
        await ask(model(recorder))
    assert len(recorder.bodies) == 4


async def test_no_fallback_configured_fails_after_the_main_model() -> None:
    recorder = Recorder([httpx.Response(402)])
    with pytest.raises(PlannerUnavailable):
        await ask(model(recorder, fallback=None))


async def test_answers_are_clamped() -> None:
    phrases = [
        {"id": "P1", "base": ["S1", "S99", "S2", "S3", "S4"], "overlay": ["C9", "C1"],
         "fit": "shows", "why": "a"},
        {"id": "P2", "base": ["S1"], "overlay": ["C2"], "fit": "none", "why": "b"},
        {"id": "P7", "base": ["S1"], "overlay": [], "fit": "shows", "why": "unknown phrase"},
    ]  # fmt: skip
    answers = await ask(model(Recorder([answer(phrases)])))
    assert answers == [
        PhraseAnswer("P1", ["S1", "S2", "S3"], "C1", "a"),
        PhraseAnswer("P2", [], None, "b"),
    ]


async def test_no_card_sheet_sends_only_the_shot_sheets() -> None:
    recorder = Recorder([answer(GOOD)])
    await ask(model(recorder), cards=None)
    content = recorder.bodies[0]["messages"][1]["content"]
    assert sum(part["type"] == "image_url" for part in content) == len(SHEETS)
