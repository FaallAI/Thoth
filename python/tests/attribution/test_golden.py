"""Every golden case replays offline to its expected attribution (ADR 0001 parity)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tests.attribution.replay import parse_report, replay_ports
from thoth_control_plane.attribution.service import SourceAttributor

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "attribution"
CASES = sorted(FIXTURES.glob("*.json"))
DEPARTURES = {
    "repost_first",
    "visual_match",
    "no_story_search",
    "constrained_credit",
    "logo_by_decision",
    "scout_not_run",
    # Spec 2026-10-13: Scout replaced an original reaction with its subject.
    "reaction_original",
}


def _video(case: dict[str, Any]) -> Path | None:
    key = case.get("repost_frames")
    return Path(f"{key}.mp4") if key and key in case["frames"] else None


@pytest.mark.asyncio
@pytest.mark.parametrize("path", CASES, ids=lambda path: path.stem)
async def test_a_golden_case_replays_to_its_expected_attribution(path: Path) -> None:
    case = json.loads(path.read_text(encoding="utf-8"))
    report = parse_report(case["report"])

    outcome = await SourceAttributor(replay_ports(case)).identify("wf_golden", report, _video(case))

    attribution = outcome.attribution
    expected = case["expected"]
    assert attribution.verdict == expected["verdict"]
    source = str(attribution.source.canonical_url) if attribution.source else None
    assert source == expected.get("source_url")
    if "confidence" in expected:
        assert attribution.confidence == expected["confidence"]
    python_main = expected.get("source_url") or str(report.source.canonical_url)
    assert python_main == case["scout"]["main_url"] or case.get("departure") in DEPARTURES


def test_there_is_at_least_the_synthetic_case() -> None:
    assert any(path.stem == "synthetic_reference" for path in CASES)
