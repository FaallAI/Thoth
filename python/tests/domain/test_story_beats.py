"""Story beats on the server (spec 2026-10-31 auto-draft), held to Studio's story_beats.ts.

The cases live in ``dashboard/src/features/studio/story_beat_cases.json``; their expected values
are computed by the dashboard functions, which stay the reference.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from thoth_control_plane.domain.edit_document_v2 import EditDocumentV2
from thoth_control_plane.domain.story_beats import ROLE_BEAT, beat_spans, clip_beats
from thoth_control_plane.domain.studio_imports import SourceRole

CASES = json.loads(
    (Path(__file__).parents[3] / "dashboard/src/features/studio/story_beat_cases.json").read_text(
        "utf-8"
    )
)


def test_every_import_role_and_both_added_beats_have_a_beat() -> None:
    assert set(ROLE_BEAT) == set(SourceRole.__args__) | {"hook", "outro"}  # type: ignore[attr-defined]


@pytest.mark.parametrize("case", CASES["cases"], ids=[case["name"] for case in CASES["cases"]])
def test_the_shared_beat_cases(case: dict[str, Any]) -> None:
    document = EditDocumentV2.model_validate(case["document"])
    beats = clip_beats(document, case["inventory_roles"])
    assert {clip.clip_id: beats.get(clip.clip_id) for clip in document.clips} == case[
        "expected_clip_beats"
    ]
    assert [
        {
            "beat": span.beat,
            "clip_ids": span.clip_ids,
            "start_frame": span.start_frame,
            "duration_in_frames": span.duration_in_frames,
        }
        for span in beat_spans(document, case["inventory_roles"])
    ] == case["expected_spans"]
