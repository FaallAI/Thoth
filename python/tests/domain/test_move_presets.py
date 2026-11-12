"""The move presets Studio offers, ported for style templates (spec 2026-11-10)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from thoth_control_plane.domain.move_presets import move_preset

CASES = json.loads(
    (
        Path(__file__).resolve().parents[3] / "dashboard/src/features/studio/move_preset_cases.json"
    ).read_text(encoding="utf-8")
)


@pytest.mark.parametrize("case", CASES, ids=[case["name"] for case in CASES])
def test_shared_case(case: dict[str, Any]) -> None:
    moves = move_preset(case["kind"], case["duration"], case["fps"])
    assert [move.model_dump() for move in moves] == case["expected"]


def test_a_one_frame_preset_is_one_keyframe() -> None:
    assert len(move_preset("push_in", 1, 30)) == 1
