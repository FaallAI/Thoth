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


@pytest.mark.asyncio
async def test_static_leases_hand_out_the_cookie_session_for_its_platforms() -> None:
    from datetime import UTC, datetime

    from tests.attribution.capture_golden import StaticLeases
    from thoth_control_plane.acquisition.accounts.access import SessionAccess
    from thoth_control_plane.acquisition.accounts.cookies import parse_cookies

    access = SessionAccess(
        parse_cookies(
            "tiktok",
            "\t".join([".tiktok.com", "TRUE", "/", "TRUE", "1893456000", "sessionid", "s"]) + "\n",
            now=datetime(2026, 10, 9, tzinfo=UTC),
        )
    )
    leases = StaticLeases({"tiktok": access})

    assert (await leases.mode("tiktok"), await leases.mode("x")) == ("fallback", "anonymous")
    lease = await leases.lease("tiktok")
    assert lease is not None and lease.access is access
    assert await leases.lease("x") is None
    await leases.release(lease, "success")


@pytest.mark.asyncio
async def test_a_reaction_case_records_its_speech_and_answers() -> None:
    from tests.attribution.test_service import VIDEO, _reaction_case, _reaction_report

    recorded = await record_case(
        replay_ports(_reaction_case()),
        parse_report(_reaction_report()),
        VIDEO,
        case="reaction",
        expected={"verdict": "original", "source_url": None},
        scout={"main_url": None, "note": ""},
        departure="reaction_original",
    )

    assert json.loads(json.dumps(recorded)) == recorded
    assert recorded["cuts"] == [3.0]
    assert recorded["transcript"] == {
        "language": "id",
        "segments": [[0.5, 2.5, "klip aslinya"], [5.0, 30.0, "ini isu baru"]],
    }
    assert recorded["turns"] == [[0.0, 3.0, 0], [4.0, 35.0, 1]]
    assert recorded["assessment"] == {"contribution": 0.8, "discussion": 0.7}
    comment = recorded["report"]["comments"][0]
    assert (comment["text"], comment.get("card")) == ("setuju sama kakaknya", None)
    assert "detikjatim" in recorded["discovery"]["by_handle"]
    replayed = await SourceAttributor(replay_ports(recorded)).identify(
        "wf_golden", parse_report(recorded["report"]), Path(f"{recorded['repost_frames']}.mp4")
    )
    assert replayed.attribution.verdict == "original"
