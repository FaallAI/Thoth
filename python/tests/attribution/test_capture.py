"""The capture tool records what the ports answered; a recorded case replays identically."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.attribution.capture_golden import record_case
from tests.attribution.replay import parse_report, replay_ports
from thoth_control_plane.attribution.service import SourceAttributor

SYNTHETIC = (
    Path(__file__).resolve().parents[1] / "fixtures" / "attribution" / "synthetic_reference.json"
)


@pytest.mark.asyncio
async def test_a_recorded_case_replays_to_the_same_attribution() -> None:
    source = json.loads(SYNTHETIC.read_text(encoding="utf-8"))
    report = parse_report(source["report"])

    recorded = await record_case(
        replay_ports(source),
        report,
        Path("repost.mp4"),
        case="roundtrip",
        expected=source["expected"],
        scout=source["scout"],
        departure="visual_match",
    )

    assert json.loads(json.dumps(recorded)) == recorded  # plain JSON only
    replayed = await SourceAttributor(replay_ports(recorded)).identify(
        "wf_golden", parse_report(recorded["report"]), Path(f"{recorded['repost_frames']}.mp4")
    )
    assert replayed.attribution.verdict == "replaced"
    assert set(recorded["acquired"]) == set(source["acquired"])  # wide tuning saw both
