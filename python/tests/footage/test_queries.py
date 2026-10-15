"""Footage queries: Scout's footage_objects prompt plus an English visual per object."""

from __future__ import annotations

from thoth_control_plane.footage.queries import (
    FootageQueryAnswer,
    footage_objects,
    query_prompt,
    top_comments,
)


def test_no_text_means_no_prompt() -> None:
    assert query_prompt("", "  ", "") is None


def test_the_prompt_carries_the_texts_bounded() -> None:
    prompt = query_prompt("d" * 900, "HEADLINE", "c" * 900)
    assert prompt is not None
    assert "d" * 700 in prompt and "d" * 701 not in prompt
    assert "HEADLINE" in prompt
    assert "c" * 600 in prompt and "c" * 601 not in prompt
    assert '"visual"' in prompt


def test_objects_are_cleaned_composed_and_capped() -> None:
    answer = FootageQueryAnswer.model_validate(
        {
            "subjects": ["Nvidia", "jensen"],
            "objects": [
                {"name": "Chip AI", "visual": "a close-up of a computer chip"},
                {"name": "chip ai", "visual": "duplicate"},
                {"name": "data center nvidia", "visual": "rows of server racks"},
                {"name": "", "visual": "empty name"},
                {"name": "x" * 41, "visual": "too long"},
                {"name": "kartu grafis", "visual": " "},
                {"name": "gpu", "visual": "a graphics card"},
                {"name": "laptop", "visual": "a gaming laptop"},
                {"name": "pabrik", "visual": "a factory floor"},
            ],
        }
    )
    objects = footage_objects(answer)
    assert [o.query for o in objects] == [
        "chip ai nvidia",
        "data center nvidia",
        "gpu nvidia",
        "laptop nvidia",
    ]
    assert objects[0].visual == "a close-up of a computer chip"


def test_objects_without_a_subject_stay_bare() -> None:
    answer = FootageQueryAnswer.model_validate(
        {"subjects": [], "objects": [{"name": "longsor", "visual": "a landslide"}]}
    )
    assert [o.query for o in footage_objects(answer)] == ["longsor"]


def test_null_fields_do_not_lose_the_answer() -> None:
    answer = FootageQueryAnswer.model_validate(
        {"subjects": None, "objects": [{"name": "banjir", "visual": None}, None]}
    )
    assert footage_objects(answer) == []


def test_top_comments_by_likes() -> None:
    joined = top_comments([("pertama", 1), ("teratas", 50), ("", 99), ("kedua", 10)])
    assert joined == "teratas • kedua • pertama"
