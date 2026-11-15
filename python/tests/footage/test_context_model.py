"""The card model adapter: OpenRouter JSON, the next model on any failure (spec 4.1)."""

from __future__ import annotations

import json
from pathlib import Path

import httpx

from thoth_control_plane.footage.adapters.context_model import OpenRouterCardModel

CARD = (
    Path(__file__).resolve().parents[1] / "fixtures" / "footage" / "context" / "mutant_card.json"
).read_text(encoding="utf-8")


def _answer(content: str | None) -> dict[str, object]:
    return {
        "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    }


async def test_an_empty_answer_falls_to_the_next_model() -> None:
    asked: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        model = json.loads(request.content)["model"]
        asked.append(model)
        return httpx.Response(200, json=_answer(None if model == "first" else CARD))

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    model = OpenRouterCardModel("key", ["first", "second"], client=client)
    result = await model.card("system", "material")
    assert asked == ["first", "second"]
    assert result is not None and len(result.people) == 2


async def test_every_model_failing_gives_none() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    model = OpenRouterCardModel("key", ["first", "second"], client=client)
    assert await model.card("system", "material") is None
