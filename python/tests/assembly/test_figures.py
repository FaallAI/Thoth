"""Figures: who the post is about, or nothing; the model only proposes, code normalizes."""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from thoth_control_plane.assembly.figures import (
    FigureAnswer,
    figure_prompt,
    normalize_figures,
)


def _require_module(name: str) -> None:
    # Operator, 2026-10-11/13: a required tool missing is a failure, never a skip.
    import importlib.util

    if importlib.util.find_spec(name) is None:
        pytest.fail(f"{name} is required for this test and is not installed")


def test_no_text_means_no_prompt() -> None:
    assert figure_prompt("", "  ", "") is None


def test_prompt_carries_bounded_text() -> None:
    prompt = figure_prompt("Judul", "d" * 900, "HEADLINE")

    assert prompt is not None
    assert "[TITLE]: Judul" in prompt and "[HEADLINE]: HEADLINE" in prompt
    assert "d" * 600 in prompt and "d" * 601 not in prompt


def test_normalization_trims_defaults_and_caps() -> None:
    answer = FigureAnswer.model_validate(
        {
            "figures": [
                {"name": "  Prabowo Subianto ", "type": "Person", "role": "Presiden"},
                {"name": "", "type": "person"},
                {"name": "Persija", "type": "club"},
                *({"name": f"Tokoh {n}", "type": "person"} for n in range(6)),
            ]
        }
    )

    figures = normalize_figures(answer)

    assert [(f.name, f.type) for f in figures[:2]] == [
        ("Prabowo Subianto", "person"),
        ("Persija", "person"),
    ]
    assert len(figures) == 5


@pytest.mark.asyncio
@respx.mock
async def test_adapter_reads_structured_figures_and_degrades_to_none() -> None:
    _require_module("openai")
    from thoth_control_plane.assembly.adapters.figures import (
        OPENROUTER_BASE_URL,
        AgnoFigureModel,
    )

    route = respx.post(f"{OPENROUTER_BASE_URL}/chat/completions")
    model = AgnoFigureModel("synthetic-key", "deepseek/deepseek-v4-flash-0731")
    content = json.dumps({"figures": [{"name": "Anies Baswedan", "type": "person"}]})
    route.mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "c1",
                "object": "chat.completion",
                "created": 0,
                "model": "m",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": content},
                    }
                ],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            },
        )
    )

    answer = await model.read("prompt")

    assert answer is not None and answer.figures[0].name == "Anies Baswedan"
    assert "deepseek/deepseek-v4-flash-0731" in route.calls.last.request.content.decode()
    route.mock(return_value=httpx.Response(500, json={"error": "down"}))
    assert await model.read("prompt") is None


def test_null_fields_from_the_model_are_tolerated() -> None:
    # Review 2026-10-12: Scout coerced with `String(f.role || '')`; a null must not cost the
    # whole answer.
    answer = FigureAnswer.model_validate(
        {
            "figures": [
                {"name": "Najwa Shihab", "type": None, "role": None, "description": None},
                {"name": None, "type": "person"},
            ]
        }
    )

    assert [(f.name, f.type, f.role) for f in normalize_figures(answer)] == [
        ("Najwa Shihab", "person", "")
    ]
