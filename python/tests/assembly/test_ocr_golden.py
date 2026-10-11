"""Live calibration cases replay offline through the production OCR path to their verdicts.

Each fixture holds the RapidOCR boxes production read, the region tracker's and the caption
judge's answers, and the verdict the operator confirmed against the video (`expected`).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tests.assembly.ocr_replay import replay

CASES = sorted((Path(__file__).parents[1] / "fixtures" / "assembly" / "ocr").glob("*.json"))


def _case(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("path", CASES, ids=[path.stem for path in CASES])
def test_golden_ocr_verdict(path: Path) -> None:
    case = _case(path)
    assert case["expected"] is not None, "the operator has not confirmed this verdict yet"

    ocr = replay(case)

    expected = case["expected"]
    assert ocr.outcome == expected["outcome"]
    assert ocr.trim_start == pytest.approx(expected["trim_start"], abs=0.01)
    assert len(ocr.subtitle_blur) == expected["blur_count"]
