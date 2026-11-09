"""Clip moves: the shared cases the composition also runs (spec 2026-11-09, 3.1)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from thoth_control_plane.domain.clip_moves import (
    fit_move_list,
    move_at,
    shift_moves,
    split_moves,
    stretch_moves,
)
from thoth_control_plane.domain.edit_document_v2 import MoveKeyframe

CASES_PATH = (
    Path(__file__).resolve().parents[3] / "packages/remotion-composition/src/move_cases.json"
)
CASES = json.loads(CASES_PATH.read_text(encoding="utf-8"))["cases"]


def keyframes(raw: list[dict[str, Any]]) -> list[MoveKeyframe]:
    return [MoveKeyframe.model_validate(item) for item in raw]


def dumped(moves: list[MoveKeyframe]) -> list[dict[str, Any]]:
    return [move.model_dump() for move in moves]


def approx_moves(raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            **item,
            "scale": pytest.approx(item["scale"]),
            "x": pytest.approx(item["x"]),
            "y": pytest.approx(item["y"]),
        }
        for item in raw
    ]


@pytest.mark.parametrize("case", CASES, ids=[case["name"] for case in CASES])
def test_shared_move_case(case: dict[str, Any]) -> None:
    moves, args, expect = keyframes(case["moves"]), case["args"], case["expect"]
    match case["op"]:
        case "at":
            assert list(move_at(moves, args["frame"])) == pytest.approx(expect)
        case "shift":
            assert dumped(shift_moves(moves, args["delta"])) == approx_moves(expect)
        case "split":
            left, right = split_moves(moves, args["at"])
            assert dumped(left) == approx_moves(expect[0])
            assert dumped(right) == approx_moves(expect[1])
        case "stretch":
            assert dumped(stretch_moves(moves, args["old"], args["new"])) == approx_moves(expect)
        case "fit":
            assert dumped(fit_move_list(moves, args["duration"])) == approx_moves(expect)
        case other:
            raise AssertionError(f"unknown case op {other}")
