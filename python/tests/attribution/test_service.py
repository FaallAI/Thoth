"""The attribution service end to end over replayed ports."""

from __future__ import annotations

import asyncio
import copy
import json
from pathlib import Path
from typing import Any

import pytest

from tests.attribution.replay import ReplayVisionCover, parse_report, replay_ports
from thoth_control_plane.attribution.ports import AttributionError
from thoth_control_plane.attribution.service import SourceAttributor, Tuning

FIXTURE = json.loads(
    (
        Path(__file__).resolve().parents[1] / "fixtures" / "tiktok" / "source_report_v3.json"
    ).read_text(encoding="utf-8")
)
REPOST_URL = "https://www.tiktok.com/@detikjatim/video/7677496203042360594"
SOURCE = "vincentius.christ76"
VIDEO = Path("repost.mp4")


def _url(n: int) -> str:
    return f"https://www.tiktok.com/@{SOURCE}/video/{7677137235434687000 + n}"


def _report(
    *,
    owner: str = "detikjatim",
    url: str = REPOST_URL,
    text: str = "",
    published: str | None = "2026-08-24T07:26:32Z",
    duration: float = 90.0,
    video: bool = True,
) -> dict[str, Any]:
    data = copy.deepcopy(FIXTURE)
    data["source"]["canonical_url"] = url
    data["post"].update(
        owner_handle=owner, text=text, published_at=published, post_id=url.rsplit("/", 1)[1]
    )
    data["comments"] = []
    if video:
        data["media"][0]["duration_seconds"] = duration
    else:
        data["media"] = []
    return data


def _frames(count: int, boxes: dict[int, list[Any]] | None = None) -> list[dict]:
    return [{"second": float(n), "boxes": (boxes or {}).get(n, [])} for n in range(count)]


def _video(n: int, published: str) -> dict[str, Any]:
    return {
        "post_id": str(7677137235434687000 + n),
        "owner_handle": SOURCE,
        "canonical_url": _url(n),
        "published_at": published,
        "duration_seconds": 124.0,
        "engagement": {"play": 1},
    }


def _case(**overrides: Any) -> dict[str, Any]:
    case: dict[str, Any] = {
        "frames": {
            "repost": _frames(3, {0: [["♪ vincentius.christ76   detikjatim", 0.88, 0.93]]}),
            "original": _frames(5),
            "other": _frames(2),
        },
        # Inliers each repost frame finds in a candidate: the original holds two of three.
        "matches": {"original": [120, 64, 0], "other": [3, 0, 12]},
        "cover": {"headline": "BANJIR DI JATIM", "scene": "a flooded street", "icon": "a note"},
        "decisions": {
            "is_repost": 0.95,
            "handle": SOURCE,
            "handle_probability": 0.9,
            "platform": "tiktok",
            "platform_probability": 0.9,
        },
        "discovery": {
            "videos": [
                _video(1, "2026-08-24T10:00:00Z"),  # after the repost: filtered
                _video(2, "2026-08-22T09:00:00Z"),  # two days before: second
                _video(3, "2026-08-23T08:13:31Z"),  # 23 hours before: first, the original
            ]
        },
        "acquired": {
            _url(3): {"report": _report(owner=SOURCE, url=_url(3)), "frames": "original"},
            _url(2): {"report": _report(owner=SOURCE, url=_url(2)), "frames": "other"},
        },
    }
    case.update(overrides)
    return case


async def _identify(case: dict[str, Any], report: dict[str, Any] | None = None, **tuning: Any):
    ports = replay_ports(case)
    attributor = SourceAttributor(ports, Tuning(**tuning))
    video = VIDEO if (report or {}).get("media", [1]) else None
    outcome = await attributor.identify("wf_ref", parse_report(report or _report()), video)
    return outcome, ports


@pytest.mark.asyncio
async def test_the_reference_pair_resolves_to_the_credited_original() -> None:
    outcome, ports = await _identify(_case(), finalist_concurrency=1)
    attribution = outcome.attribution

    assert (attribution.verdict, attribution.confidence) == ("replaced", "high")
    assert attribution.source is not None and str(attribution.source.canonical_url) == _url(3)
    assert outcome.original is not None and outcome.original.candidate_id == "wf_ref-c1"
    assert ports.acquirer.acquired == ["wf_ref-c1"]  # early exit: c2 is never fetched
    assert attribution.candidates == {
        "discovered": 3,
        "filtered_window": 1,
        "matched": 1,
        "not_evaluated": 1,
    }
    details = {item.detail for item in attribution.evidence}
    assert {
        "@vincentius.christ76",
        "credit @vincentius.christ76",
        "2 repost frames hold it, up to 120 inliers",
    } <= details
    assert ports.decisions.calls[0][1] == [SOURCE]


@pytest.mark.asyncio
async def test_with_concurrency_two_the_extra_finalist_is_discarded() -> None:
    outcome, ports = await _identify(_case())

    assert outcome.attribution.verdict == "replaced"
    assert ports.acquirer.acquired == ["wf_ref-c1", "wf_ref-c2"]
    assert ports.acquirer.discarded == ["wf_ref-c2"]
    assert outcome.attribution.candidates["no_match"] == 1


@pytest.mark.asyncio
async def test_a_caption_convention_overrides_the_model() -> None:
    _, ports = await _identify(_case(), _report(text="Lokasi [📸 @ig.creator]"))

    assert ports.discoverer.calls == [("instagram", "ig.creator")]


@pytest.mark.asyncio
async def test_no_credit_decides_original_or_unresolved_by_the_repost_probability() -> None:
    quiet = _case()
    quiet["frames"]["repost"][0]["boxes"] = []
    quiet["decisions"] = {**quiet["decisions"], "handle": None, "handle_probability": 0.0}

    quiet["decisions"]["is_repost"] = 0.1
    original, _ = await _identify(quiet)
    assert (original.attribution.verdict, original.attribution.confidence) == ("original", "high")

    quiet["decisions"]["is_repost"] = 0.9
    unresolved, _ = await _identify(quiet)
    assert (unresolved.attribution.verdict, unresolved.attribution.reason) == (
        "unresolved",
        "no_credit",
    )


@pytest.mark.asyncio
async def test_a_threads_credit_or_a_failed_discovery_is_unresolved() -> None:
    threads = _case()
    threads["decisions"] = {**threads["decisions"], "platform": "threads"}
    outcome, _ = await _identify(threads)
    assert outcome.attribution.reason == "discovery_unsupported"

    failed, _ = await _identify(_case(discovery=None))
    assert failed.attribution.reason == "discovery_failed"


@pytest.mark.asyncio
async def test_unmeasured_commentary_and_reaction_finalists_are_skipped() -> None:
    both = {"original": "commentary", "other": "commentary"}
    commentary, ports = await _identify(_case(classify=both, unmatchable=["repost"]))
    assert (commentary.attribution.verdict, commentary.attribution.reason) == (
        "unresolved",
        "no_match",
    )
    assert commentary.attribution.candidates["commentary"] == 2
    assert sorted(ports.acquirer.discarded) == ["wf_ref-c1", "wf_ref-c2"]

    speaking = _case(unmatchable=["repost"])
    speaking["frames"]["original"] = _frames(
        5, {n: [[f"kata ke {n}", 0.70, 0.76]] for n in range(5)}
    )
    reaction, _ = await _identify(speaking)
    assert reaction.attribution.candidates["reaction"] == 1


@pytest.mark.asyncio
async def test_a_visual_match_outranks_a_commentary_label() -> None:
    # Live captures: vision called talking-head originals "commentary" while ORB matched them.
    outcome, _ = await _identify(_case(classify={"original": "commentary"}))

    assert (outcome.attribution.verdict, outcome.attribution.confidence) == ("replaced", "high")
    source = outcome.attribution.source
    assert source is not None and str(source.canonical_url) == _url(3)


@pytest.mark.asyncio
async def test_a_weak_match_on_one_shared_frame_is_no_match() -> None:
    # A logo or an end card the account puts on every video: a few dozen inliers at most.
    weak = _case(matches={"original": [30, 0, 0], "other": [3, 0, 12]})

    outcome, _ = await _identify(weak)

    assert (outcome.attribution.verdict, outcome.attribution.reason) == ("unresolved", "no_match")


@pytest.mark.asyncio
async def test_a_repost_whose_frames_fail_is_unresolved() -> None:
    broken = _case()
    del broken["frames"]["repost"]  # ffmpeg missing, crashed, or timed out

    outcome, ports = await _identify(broken)

    assert (outcome.attribution.verdict, outcome.attribution.reason) == (
        "unresolved",
        "frames_failed",
    )
    assert ports.acquirer.acquired == []


@pytest.mark.asyncio
async def test_a_cancelled_attribution_still_discards_its_finalists() -> None:
    case = _case()
    ports = replay_ports(case)

    class _Cancelling(type(ports.frames)):  # type: ignore[misc]
        async def frames(self, video: Path, *, fps: float, seconds: float | None = None) -> Any:
            if video.stem == "original":
                raise asyncio.CancelledError
            return await super().frames(video, fps=fps, seconds=seconds)

    object.__setattr__(ports, "frames", _Cancelling(case["frames"]))
    attributor = SourceAttributor(ports, Tuning(finalist_concurrency=1))

    with pytest.raises(asyncio.CancelledError):
        await attributor.identify("wf_ref", parse_report(_report()), VIDEO)
    assert ports.acquirer.discarded == ["wf_ref-c1"]


@pytest.mark.asyncio
async def test_a_candidate_whose_frames_fail_is_counted_as_frames_failed() -> None:
    case = _case()
    case["acquired"][_url(3)]["frames"] = "unreadable"  # ffmpeg fails on the candidate

    outcome, _ = await _identify(case)

    assert outcome.attribution.candidates["frames_failed"] == 1


@pytest.mark.asyncio
async def test_handles_read_by_vision_keep_their_origin() -> None:
    case = _case()
    case["cover"] = {**case["cover"], "handles": ["kreator.asli"]}

    outcome, _ = await _identify(case)

    pairs = {(item.kind, item.detail) for item in outcome.attribution.evidence}
    assert ("cover_vision", "handle: @kreator.asli") in pairs
    assert ("frame_text", "@kreator.asli") not in pairs


@pytest.mark.asyncio
async def test_candidate_sampling_stops_at_the_candidate_limit() -> None:
    case = _case()
    ports = replay_ports(case)
    asked: list[tuple[str, float | None]] = []

    class _Spy(type(ports.frames)):  # type: ignore[misc]
        async def frames(self, video: Path, *, fps: float, seconds: float | None = None) -> Any:
            asked.append((video.stem, seconds))
            return await super().frames(video, fps=fps, seconds=seconds)

    object.__setattr__(ports, "frames", _Spy(case["frames"]))
    await SourceAttributor(ports, Tuning(candidate_seconds=120.0)).identify(
        "wf_ref", parse_report(_report()), VIDEO
    )

    assert ("original", 120.0) in asked
    assert ("repost", None) in asked


@pytest.mark.asyncio
async def test_a_repost_without_video_replaces_with_low_confidence() -> None:
    outcome, ports = await _identify(_case(), _report(video=False, text="via @vincentius.christ76"))

    assert (outcome.attribution.verdict, outcome.attribution.confidence) == ("replaced", "low")
    assert "repost" not in ports.frames.calls


@pytest.mark.asyncio
async def test_flat_repost_frames_leave_the_match_unmeasured() -> None:
    flat = _case()
    flat["unmatchable"] = ["repost"]

    outcome, _ = await _identify(flat)

    assert (outcome.attribution.verdict, outcome.attribution.confidence) == ("replaced", "low")
    assert outcome.attribution.candidates["unmeasured"] == 2  # both finalists, none measurable


@pytest.mark.asyncio
async def test_self_credit_is_never_a_credit() -> None:
    own = _case()
    own["frames"]["repost"][0]["boxes"] = [["@detikjatim", 0.88, 0.93]]
    own["decisions"] = {**own["decisions"], "handle": None, "is_repost": 0.2}

    outcome, ports = await _identify(own)

    assert ports.decisions.calls[0][1] == []
    assert outcome.attribution.verdict == "original"


@pytest.mark.asyncio
async def test_external_content_failures_degrade_instead_of_failing() -> None:
    case = _case()
    case["acquired"] = {_url(2): case["acquired"][_url(2)]}  # the original cannot be acquired
    ports = replay_ports(case)

    outcome = await SourceAttributor(ports).identify("wf_ref", parse_report(_report()), VIDEO)

    assert (outcome.attribution.verdict, outcome.attribution.reason) == ("unresolved", "no_match")
    assert outcome.attribution.candidates["acquisition_failed"] == 1


@pytest.mark.asyncio
async def test_a_misread_handle_is_corrected_from_a_near_variant_in_the_evidence() -> None:
    case = _case(
        cover={"headline": "", "scene": "", "icon": "", "handles": ["@vincentius.christ76"]},
        decisions={
            "is_repost": 0.95,
            "handle": "vincentius.christ7",
            "handle_probability": 0.9,
            "platform": "tiktok",
            "platform_probability": 0.9,
        },
    )
    case["frames"]["repost"][0]["boxes"] = [["@vincentius.christ7", 0.88, 0.93]]
    case["discovery"] = {"by_handle": {SOURCE: case["discovery"]["videos"]}}

    outcome, ports = await _identify(case, finalist_concurrency=1)

    assert ports.decisions.calls[0][1] == ["vincentius.christ7", SOURCE]
    assert ports.discoverer.calls == [("tiktok", "vincentius.christ7"), ("tiktok", SOURCE)]
    assert outcome.attribution.verdict == "replaced"
    assert "credit corrected to @vincentius.christ76" in {
        e.detail for e in outcome.attribution.evidence
    }


class _RaisingVision:
    async def read_cover(self, frames: Any) -> Any:
        raise AttributionError("vision_unavailable")

    async def classify(self, frames: Any) -> Any:
        raise AttributionError("vision_unavailable")


class _RaisingDecisions:
    async def decide(self, evidence: Any, handles: Any) -> Any:
        raise AttributionError("decision_unavailable")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("port", "code"), [("vision", "vision_unavailable"), ("decisions", "decision_unavailable")]
)
async def test_a_failing_vision_or_decision_stops_attribution(port: str, code: str) -> None:
    ports = replay_ports(_case())
    object.__setattr__(ports, port, _RaisingVision() if port == "vision" else _RaisingDecisions())

    with pytest.raises(AttributionError) as raised:
        await SourceAttributor(ports).identify("wf_ref", parse_report(_report()), VIDEO)
    assert raised.value.code == code


@pytest.mark.asyncio
async def test_a_failing_classification_still_discards_finalists() -> None:
    case = _case(matches={}, unmatchable=["repost"])  # unmeasured: the genre check runs
    ports = replay_ports(case)
    vision = _RaisingVision()
    object.__setattr__(vision, "read_cover", ReplayVisionCover(case))
    object.__setattr__(ports, "vision", vision)

    with pytest.raises(AttributionError):
        await SourceAttributor(ports, Tuning(finalist_concurrency=1)).identify(
            "wf_ref", parse_report(_report()), VIDEO
        )
    assert ports.acquirer.acquired and ports.acquirer.discarded == ports.acquirer.acquired


@pytest.mark.asyncio
async def test_a_missing_ffmpeg_stops_attribution() -> None:
    from thoth_control_plane.attribution.adapters.frames import ToolMissing

    class _NoFfmpeg:
        async def frames(self, video: Path, *, fps: float, seconds: float | None = None) -> Any:
            raise ToolMissing("ffmpeg_missing")

    ports = replay_ports(_case())
    object.__setattr__(ports, "frames", _NoFfmpeg())

    with pytest.raises(AttributionError) as raised:
        await SourceAttributor(ports).identify("wf_ref", parse_report(_report()), VIDEO)
    assert raised.value.code == "ffmpeg_missing"


@pytest.mark.asyncio
async def test_vision_sees_frames_from_every_long_shot() -> None:
    case = _case(cuts=[1.5])
    case["frames"]["repost"] = _frames(40, {0: case["frames"]["repost"][0]["boxes"]})
    ports = replay_ports(case)

    await SourceAttributor(ports).identify("wf_ref", parse_report(_report()), VIDEO)

    seconds = ports.vision.cover_seconds
    assert seconds[:2] == [0.0, 1.0] and any(s > 10 for s in seconds) and len(seconds) <= 6


REACTION_COVER = {
    "headline": "",
    "scene": "a woman talks to the camera after a news clip",
    "icon": "",
    "reaction_shape": "clip_then_talk",
    "subject_media": "video",
    "shows": ["subject", "subject", "creator", "creator"],
}
OWNER_VIDEOS = [
    {
        "post_id": str(7677000000000000500 + n),
        "owner_handle": "detikjatim",
        "canonical_url": f"https://www.tiktok.com/@detikjatim/video/{7677000000000000500 + n}",
        "engagement": {"play": 1000},
    }
    for n in range(5)
]


def _reaction_case(**overrides: Any) -> dict[str, Any]:
    case = _case(
        cover=REACTION_COVER,
        cuts=[3.0],
        transcript={
            "language": "id",
            "segments": [[0.5, 2.5, "klip aslinya"], [5.0, 30.0, "ini isu baru"]],
        },
        turns=[[0.0, 3.0, 0], [4.0, 35.0, 1]],
        assessment={"contribution": 0.8, "discussion": 0.7},
    )
    case["frames"]["repost"] = _frames(40, {0: case["frames"]["repost"][0]["boxes"]})
    case["discovery"] = {
        "by_handle": {SOURCE: case["discovery"]["videos"], "detikjatim": OWNER_VIDEOS}
    }
    case.update(overrides)
    return case


def _reaction_report(**engagement: int) -> dict[str, Any]:
    report = _report()
    report["post"]["engagement"] = engagement or {"play": 5000}
    report["comments"] = [
        {"comment_id": "c0001", "author": "a.b", "text": "setuju sama kakaknya", "likes": 3}
    ]
    return report


@pytest.mark.asyncio
async def test_a_reaction_that_adds_and_is_discussed_is_an_original() -> None:
    outcome, ports = await _identify(_reaction_case(), _reaction_report())

    assert outcome.attribution.verdict == "original"
    assert outcome.original is None and ports.acquirer.acquired == []
    reaction = [e.detail for e in outcome.attribution.evidence if e.kind == "reaction"]
    assert len(reaction) == 1 and "original_reaction" in reaction[0]
    assert "isu baru" not in reaction[0]  # no speech in the artifact
    state = ports.decisions.assessed[0]
    assert state["creator_speech"] == "ini isu baru"
    assert state["subject_speech"] == "klip aslinya"
    assert ports.discoverer.calls == [("tiktok", "detikjatim")]


@pytest.mark.asyncio
async def test_a_reaction_to_a_text_post_is_an_original_without_transcription() -> None:
    case = _reaction_case(cover={**REACTION_COVER, "subject_media": "text"})

    outcome, ports = await _identify(case, _reaction_report())

    assert outcome.attribution.verdict == "original"
    assert ports.transcriber.calls == 0 and ports.decisions.assessed == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"assessment": {"contribution": 0.2, "discussion": 0.9}}, "no_new_contribution"),
        ({"assessment": {"contribution": 0.9, "discussion": 0.1}}, "comments_not_about_creator"),
    ],
)
async def test_a_reaction_judged_a_repost_goes_on_to_find_its_video(
    change: dict[str, Any], reason: str
) -> None:
    outcome, _ = await _identify(_reaction_case(**change), _reaction_report())

    assert outcome.attribution.verdict == "replaced"
    details = [e.detail for e in outcome.attribution.evidence if e.kind == "reaction"]
    assert reason in details[0]


@pytest.mark.asyncio
async def test_no_comments_or_no_baseline_keeps_it_a_repost(
    caplog: pytest.LogCaptureFixture,
) -> None:
    quiet = _reaction_report()
    quiet["comments"] = []
    unknown = _reaction_case()
    unknown["discovery"]["by_handle"]["detikjatim"] = []

    first, _ = await _identify(_reaction_case(), quiet)
    with caplog.at_level("WARNING"):
        second, _ = await _identify(unknown, _reaction_report())

    assert first.attribution.verdict == second.attribution.verdict == "replaced"
    assert "reaction baseline unavailable" in caplog.text


@pytest.mark.asyncio
async def test_a_silent_reaction_is_judged_on_text_alone() -> None:
    case = _reaction_case(transcript={"language": "", "segments": []}, turns=[])

    outcome, ports = await _identify(case, _reaction_report())

    assert ports.decisions.assessed[0]["creator_speech"] == ""
    assert outcome.attribution.verdict == "original"  # the recorded assessment decides


@pytest.mark.asyncio
async def test_a_non_reaction_never_transcribes() -> None:
    _, ports = await _identify(_case())

    assert ports.transcriber.calls == 0 and ports.decisions.assessed == []


@pytest.mark.asyncio
async def test_a_failing_transcription_stops_attribution() -> None:
    case = _reaction_case(transcript="raise:transcription_failed")

    with pytest.raises(AttributionError) as raised:
        await _identify(case, _reaction_report())
    assert raised.value.code == "transcription_failed"


@pytest.mark.asyncio
async def test_a_failing_finalist_waits_for_its_sibling_and_discards_it() -> None:
    # Review 2026-10-13: gather let the error out while the sibling was still downloading.
    case = _case(matches={}, unmatchable=["repost"])
    ports = replay_ports(case)
    vision = _RaisingVision()
    object.__setattr__(vision, "read_cover", ReplayVisionCover(case))
    object.__setattr__(ports, "vision", vision)
    inner = ports.acquirer

    class _SlowSecond:
        async def acquire(self, candidate_id: str, url: str) -> Any:
            if candidate_id.endswith("-c2"):
                await asyncio.sleep(0.2)
            return await inner.acquire(candidate_id, url)

        async def discard(self, candidate_id: str) -> None:
            await inner.discard(candidate_id)

    object.__setattr__(ports, "acquirer", _SlowSecond())

    with pytest.raises(AttributionError):
        await SourceAttributor(ports, Tuning(finalist_concurrency=2)).identify(
            "wf_ref", parse_report(_report()), VIDEO
        )
    assert sorted(inner.acquired) == ["wf_ref-c1", "wf_ref-c2"]
    assert sorted(inner.discarded) == sorted(inner.acquired)


@pytest.mark.asyncio
async def test_an_instagram_reaction_is_not_its_own_baseline() -> None:
    # Review 2026-10-13: an Instagram report id is the shortcode, discovery's is the numeric pk.
    case = _reaction_case()
    own = {
        "post_id": "3700000000000000001",
        "owner_handle": "detikjatim",
        "canonical_url": REPOST_URL,
        "engagement": {"play": 5000},
    }
    case["discovery"]["by_handle"]["detikjatim"] = [own, *OWNER_VIDEOS[:2]]

    outcome, _ = await _identify(case, _reaction_report())

    details = [e.detail for e in outcome.attribution.evidence if e.kind == "reaction"]
    assert "engagement_unknown" in details[0]


@pytest.mark.asyncio
async def test_a_reaction_too_young_to_measure_is_judged_without_engagement() -> None:
    # Spec 5.7: three hours after posting, views say nothing yet.
    from datetime import UTC, datetime

    report = _reaction_report(play=10)
    published = datetime(2026, 8, 24, 7, 26, 32, tzinfo=UTC)
    attributor = SourceAttributor(
        replay_ports(_reaction_case()),
        clock=lambda: published.replace(hour=10),
    )

    outcome = await attributor.identify("wf_ref", parse_report(report), VIDEO)

    assert outcome.attribution.verdict == "original"
    details = [e.detail for e in outcome.attribution.evidence if e.kind == "reaction"]
    assert "engagement too early" in details[0] and "original_reaction_early" in details[0]


# One label per frame sent: with a cut at 3 s, vision sees seconds 0, 1, and 21.
IMAGE_COVER = {
    **REACTION_COVER,
    "subject_media": "image",
    "shows": ["subject", "subject", "creator"],
}


@pytest.mark.asyncio
async def test_a_confirmed_image_subject_is_an_original_without_a_transcript() -> None:
    # Spec 5.8: still subject frames and only the creator's voice confirm the label.
    case = _reaction_case(cover=IMAGE_COVER, turns=[[4.0, 35.0, 1]])

    outcome, ports = await _identify(case, _reaction_report())

    assert outcome.attribution.verdict == "original"
    assert ports.transcriber.calls == 0 and ports.decisions.assessed == []


@pytest.mark.asyncio
async def test_an_image_subject_that_moves_takes_the_video_path() -> None:
    # DeOUJ60SHeI, 2026-10-13: vision called a video subject an image.
    motion = [0.0] * 39
    motion[0] = 0.3  # seconds 0 to 1, inside the subject's opening shot
    case = _reaction_case(cover=IMAGE_COVER, motion=motion)

    outcome, ports = await _identify(case, _reaction_report())

    details = [e.detail for e in outcome.attribution.evidence if e.kind == "reaction"]
    assert any("subject moves" in detail for detail in details)
    assert ports.transcriber.calls == 1 and len(ports.decisions.assessed) == 1


@pytest.mark.asyncio
async def test_an_image_subject_with_another_voice_takes_the_video_path() -> None:
    case = _reaction_case(cover=IMAGE_COVER)  # speaker 0 talks over the subject's opening

    outcome, ports = await _identify(case, _reaction_report())

    details = [e.detail for e in outcome.attribution.evidence if e.kind == "reaction"]
    assert any("another voice" in detail for detail in details)
    assert ports.transcriber.calls == 1
