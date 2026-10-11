"""The Python classifier answers exactly as Scout's on Scout's cases and 300 random ones."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from thoth_control_plane.assembly.subtitles import (
    OcrBox,
    OcrFrame,
    build_sample_times,
    classify_ocr_frames,
)

FIXTURE = json.loads(
    (Path(__file__).parents[1] / "fixtures" / "assembly" / "classifier_parity.json").read_text(
        encoding="utf-8"
    )
)


def _frames(raw: list[dict[str, Any]]) -> list[OcrFrame]:
    return [
        OcrFrame(
            t=float(frame["t"]),
            boxes=tuple(
                OcrBox(box["text"], box["x0"], box["y0"], box["x1"], box["y1"])
                for box in frame["boxes"]
            ),
            error=frame.get("error"),
        )
        for frame in raw
    ]


@pytest.mark.parametrize("case", FIXTURE["cases"], ids=[c["name"] for c in FIXTURE["cases"]])
def test_classifier_matches_scout(case: dict[str, Any]) -> None:
    verdict = classify_ocr_frames(_frames(case["frames"]), float(case["duration"]))
    expected = case["verdict"]

    assert verdict.outcome == expected["outcome"]
    assert verdict.trim_start == pytest.approx(expected["trim_start"], abs=1e-9)
    assert verdict.mute_audio is expected["mute_audio"]
    assert len(verdict.subtitle_blur) == len(expected["subtitle_blur"])
    for region, scout in zip(verdict.subtitle_blur, expected["subtitle_blur"], strict=True):
        for name in ("x", "y", "w", "h", "start", "end"):
            assert getattr(region, name) == pytest.approx(scout[name], abs=1e-9), name


@pytest.mark.parametrize(
    "case",
    FIXTURE["sampleTimes"],
    ids=[f"{c['duration']}s_{c['maxFrames']}" for c in FIXTURE["sampleTimes"]],
)
def test_sample_times_match_scout(case: dict[str, Any]) -> None:
    assert build_sample_times(float(case["duration"]), case["maxFrames"]) == pytest.approx(
        case["times"], abs=1e-9
    )


def test_every_outcome_is_covered() -> None:
    outcomes = {case["verdict"]["outcome"] for case in FIXTURE["cases"]}
    assert outcomes == {"clean", "cover", "subtitle"}
