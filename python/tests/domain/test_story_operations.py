"""Story mode's clip fields and operations (spec 2026-10-27 §5).

The cases live in ``dashboard/src/features/studio/story_operation_cases.json`` so the dashboard's
``applyTimelineOperation`` is held to exactly the same expectations.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, get_args

import pytest
from pydantic import TypeAdapter

from thoth_control_plane.domain.edit_document_operations import (
    EditDocumentOperation,
    apply_edit_operations,
)
from thoth_control_plane.domain.edit_document_v2 import AssetRef, EditDocumentV2, StoryRole
from thoth_control_plane.domain.studio_imports import SourceRole

CASES = json.loads(
    (
        Path(__file__).parents[3] / "dashboard/src/features/studio/story_operation_cases.json"
    ).read_text("utf-8")
)
OPERATIONS: TypeAdapter[list[Any]] = TypeAdapter(list[EditDocumentOperation])


@pytest.mark.parametrize("case", CASES["cases"], ids=[case["name"] for case in CASES["cases"]])
def test_story_operation_cases(case: dict[str, Any]) -> None:
    document = EditDocumentV2.model_validate(CASES["base"])
    assets = {key: AssetRef.model_validate(value) for key, value in CASES["assets"].items()}
    operations = OPERATIONS.validate_python(case["operations"])

    if case["refused"]:
        with pytest.raises(ValueError):
            apply_edit_operations(document, operations, resolved_assets=assets)
        return

    result = apply_edit_operations(document, operations, resolved_assets=assets)
    clips = {clip.clip_id: clip.model_dump(mode="json") for clip in result.clips}
    for clip_id, fields in case["expect"].items():
        assert {key: clips[clip_id][key] for key in fields} == fields


def test_old_document_round_trips() -> None:
    """A clip saved before Story mode reads as drawing nothing new."""
    payload = json.loads(json.dumps(CASES["base"]))
    for clip in payload["clips"]:
        for key in ("source_role", "motion", "emphasis"):
            clip.pop(key, None)

    document = EditDocumentV2.model_validate(payload)

    card = next(clip for clip in document.clips if clip.clip_id == "clip_comment_card_000")
    assert card.motion == "none"
    assert (card.emphasis.highlight, card.emphasis.arrow) == (False, False)
    assert all(clip.source_role is None for clip in document.clips)


def test_story_role_extends_source_role() -> None:
    assert set(get_args(StoryRole)) == set(get_args(SourceRole)) | {"hook", "outro"}
