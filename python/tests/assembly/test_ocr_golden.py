"""Live RapidOCR boxes of real videos replay through the classifier to the confirmed verdict."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from thoth_control_plane.assembly.subtitles import OcrBox, OcrFrame, classify_ocr_frames

CASES = sorted((Path(__file__).parents[1] / "fixtures" / "assembly" / "ocr").glob("*.json"))


def _case(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("path", CASES, ids=[path.stem for path in CASES])
def test_golden_ocr_verdict(path: Path) -> None:
    case = _case(path)
    assert case["expected"] is not None, "the operator has not confirmed this verdict yet"
    frames = [
        OcrFrame(frame["t"], tuple(OcrBox(*box) for box in frame["boxes"]))
        for frame in case["frames"]
    ]

    verdict = classify_ocr_frames(frames, case["duration"])

    expected = case["expected"]
    assert verdict.outcome == expected["outcome"]
    assert verdict.trim_start == pytest.approx(expected["trim_start"], abs=0.01)
    assert len(verdict.subtitle_blur) == expected["blur_count"]
