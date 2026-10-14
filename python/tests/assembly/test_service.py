"""The assembler end to end over fake ports."""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from tests.assembly.support import comment, report
from thoth_control_plane.acquisition.models import SourceReport
from thoth_control_plane.assembly.figures import FigureAnswer
from thoth_control_plane.assembly.models import MainOcr
from thoth_control_plane.assembly.ports import AssemblyError
from thoth_control_plane.assembly.service import AssemblyInputs, AssemblyPorts, ContentAssembler
from thoth_control_plane.attribution.matching import TextBox
from thoth_control_plane.attribution.models import SourceAttribution
from thoth_control_plane.attribution.ports import Frame
from thoth_control_plane.footage.models import CandidateView, RunView

NOW = datetime(2026, 10, 11, 12, 0, tzinfo=UTC)
ORIGINAL_URL = "https://www.tiktok.com/@source/video/9999999999"


class Frames:
    async def frame_at(self, video: Path, second: float, *, width: int) -> Frame:
        assert video.is_file()
        return Frame(second, b"jpeg")


class Probe:
    async def duration(self, video: Path) -> float:
        return 30.0


class Clean:
    async def read(self, frame: Frame) -> list[TextBox]:
        return []


class Figures:
    def __init__(self, answer: FigureAnswer | Exception | None = None) -> None:
        self.answer, self.prompts = answer, []

    async def read(self, prompt: str) -> FigureAnswer | None:
        self.prompts.append(prompt)
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


def attribution(verdict: str, headline: str | None = None) -> SourceAttribution:
    data: dict[str, Any] = {
        "workflow_id": "wf_a",
        "input": {
            "platform": "tiktok",
            "canonical_url": "https://www.tiktok.com/@creator/video/1234567890",
            "owner_handle": "creator",
        },
        "verdict": verdict,
        "evidence": [{"kind": "cover_vision", "detail": f"headline: {headline}"}]
        if headline
        else [],
    }
    if verdict == "replaced":
        data["source"] = {
            "platform": "tiktok",
            "canonical_url": ORIGINAL_URL,
            "owner_handle": "source",
        }
    return SourceAttribution.model_validate_json(json.dumps(data))


def touch(root: Path, *reports: SourceReport) -> None:
    for item in reports:
        for media in item.media:
            path = root / media.location
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"x")


def build(
    tmp_path: Path,
    main: SourceReport,
    *,
    verdict: str | None = None,
    original: SourceReport | None = None,
    figures: Figures | None = None,
    headline: str | None = None,
):
    touch(tmp_path, main, *([original] if original else []))
    assembler = ContentAssembler(
        AssemblyPorts(frames=Frames(), probe=Probe(), text=Clean(), figures=figures),
        clock=lambda: NOW,
    )
    return asyncio.run(
        assembler.build(
            AssemblyInputs(
                workflow_id="wf_a",
                report=main,
                attribution=attribution(verdict, headline) if verdict else None,
                original=original,
                artifact_root=tmp_path,
            )
        )
    )


def test_an_original_post_is_its_own_main(tmp_path: Path) -> None:
    content = build(tmp_path, report(profile_card=True), verdict="original")

    assert content.attribution_verdict == "original"
    assert content.main.source == "input" and content.main.kind == "video"
    assert content.main.title == "Banjir di Jakarta hari ini"
    assert content.main.ocr is not None and content.main.ocr.outcome == "clean"
    assert content.main.profile_card is not None
    assert content.figures_status == "unavailable"


def test_without_attribution_the_verdict_is_none(tmp_path: Path) -> None:
    assert build(tmp_path, report()).attribution_verdict == "none"


def test_replaced_main_is_the_original_with_both_discussions(tmp_path: Path) -> None:
    repost = report(comments=[comment("a", "ini repost", 9)])
    original = report(
        workflow_id="wf_a-c1",
        owner="source",
        url=ORIGINAL_URL,
        comments=[comment("b", "video asli", 3)],
    )

    content = build(tmp_path, repost, verdict="replaced", original=original)

    assert content.main.source == "original"
    assert str(content.main.url) == ORIGINAL_URL
    assert [(c.author, c.source) for c in content.comments] == [("a", "input"), ("b", "original")]


def test_replaced_without_the_original_report_fails(tmp_path: Path) -> None:
    with pytest.raises(AssemblyError) as raised:
        build(tmp_path, report(), verdict="replaced")
    assert raised.value.code == "original_report_missing"


def test_an_images_post_needs_no_ocr(tmp_path: Path) -> None:
    content = build(tmp_path, report(media="images"))

    assert content.main.kind == "images" and len(content.main.images) == 2
    assert content.main.ocr is None


def test_text_post_uses_its_card(tmp_path: Path) -> None:
    content = build(tmp_path, report(media="none", post_card=True))

    assert content.main.kind == "card" and content.main.card is not None


def test_text_post_without_card_fails(tmp_path: Path) -> None:
    with pytest.raises(AssemblyError) as raised:
        build(tmp_path, report(media="none"))
    assert raised.value.code == "main_media_missing"


def test_a_missing_video_file_fails(tmp_path: Path) -> None:
    assembler = ContentAssembler(
        AssemblyPorts(frames=Frames(), probe=Probe(), text=Clean(), figures=None)
    )
    with pytest.raises(AssemblyError) as raised:
        asyncio.run(
            assembler.build(
                AssemblyInputs("wf_a", report(), None, None, tmp_path)  # no file written
            )
        )
    assert raised.value.code == "main_media_missing"


def test_figures_use_title_description_and_the_cover_headline(tmp_path: Path) -> None:
    figures = Figures(
        FigureAnswer.model_validate({"figures": [{"name": "Pramono Anung", "type": "person"}]})
    )

    content = build(tmp_path, report(), verdict="original", figures=figures, headline="BANJIR LAGI")

    assert content.figures_status == "ok" and content.figures[0].name == "Pramono Anung"
    assert "[HEADLINE]: BANJIR LAGI" in figures.prompts[0]


@pytest.mark.parametrize(
    ("answer", "status"),
    [(FigureAnswer(), "none"), (None, "unavailable"), (RuntimeError("down"), "unavailable")],
)
def test_figure_failures_never_fail_the_set(tmp_path: Path, answer: Any, status: str) -> None:
    assert build(tmp_path, report(), figures=Figures(answer)).figures_status == status


class Headline:
    """A headline for two seconds, then nothing: a cover verdict."""

    async def read(self, frame: Frame) -> list[TextBox]:
        if frame.second <= 2:
            return [TextBox("BANJIR BESAR JAKARTA", 0.3, 0.36, 0.08, 0.92)]
        return []


@pytest.mark.parametrize(
    ("verdict", "trimmed"),
    [(None, True), ("unresolved", True), ("original", False)],
)
def test_only_a_possible_repost_is_trimmed(
    tmp_path: Path, verdict: str | None, trimmed: bool
) -> None:
    main = report()
    touch(tmp_path, main)
    assembler = ContentAssembler(
        AssemblyPorts(frames=Frames(), probe=Probe(), text=Headline()), clock=lambda: NOW
    )

    content = asyncio.run(
        assembler.build(
            AssemblyInputs("wf_a", main, attribution(verdict) if verdict else None, None, tmp_path)
        )
    )

    ocr = content.main.ocr
    assert ocr is not None
    assert (ocr.outcome, ocr.trim_start > 0) == (("cover", True) if trimmed else ("clean", False))


class FootageReader:
    def __init__(self, run: object, admitted: list[object]) -> None:
        self._run = run
        self._admitted = admitted

    def run(self, workflow_id: str) -> object:
        return self._run

    def admitted(self, workflow_id: str) -> list[object]:
        return self._admitted


def _clip_view(ocr: dict[str, Any]) -> CandidateView:
    return CandidateView(
        url="https://www.tiktok.com/@broll/video/7400000000000000002",
        platform="tiktok",
        source="search",
        query="banjir jakarta",
        visual="a flooded street",
        owner_handle="broll",
        caption="Banjir di jalan",
        published_at=None,
        engagement={"likes": 10},
        source_duration=40.0,
        status="admitted",
        reason=None,
        story_score=0.8,
        kind="footage",
        shows_object="yes",
        description="A flooded street.",
        media_location="reports/wf_a/footage/abc.mp4",
        media_checksum="sha256:" + "a" * 64,
        media_bytes=2048,
        clip_duration=20.0,
        clip_start=4.2,
        ocr=ocr,
        position=0,
    )


def _footage_build(tmp_path: Path, reader: FootageReader | None, figures: Figures | None = None):
    main = report()
    touch(tmp_path, main)
    assembler = ContentAssembler(
        AssemblyPorts(
            frames=Frames(), probe=Probe(), text=Clean(), figures=figures, footage=reader
        ),
        clock=lambda: NOW,
    )
    return asyncio.run(assembler.build(AssemblyInputs("wf_a", main, None, None, tmp_path)))


def _run(status: str = "done", footage_status: str | None = "ok") -> RunView:
    return RunView(workflow_id="wf_a", status=status, footage_status=footage_status, objects=[])


def _clean_ocr() -> dict[str, Any]:
    return MainOcr(
        analyzed_at=NOW,
        requested_frames=4,
        valid_frames=4,
        outcome="clean",
        trim_start=0.0,
        mute_audio=False,
    ).model_dump(mode="json")


def test_without_a_footage_reader_footage_is_disabled(tmp_path: Path) -> None:
    content = _footage_build(tmp_path, None)
    assert (content.footage, content.footage_status) == ([], "disabled")


def test_no_footage_run_is_unavailable(tmp_path: Path) -> None:
    content = _footage_build(tmp_path, FootageReader(None, []))
    assert (content.footage, content.footage_status) == ([], "unavailable")


def test_a_run_still_running_is_unavailable(tmp_path: Path) -> None:
    reader = FootageReader(_run(status="running", footage_status=None), [])
    assert _footage_build(tmp_path, reader).footage_status == "unavailable"


def test_admitted_clips_become_footage_and_feed_figures(tmp_path: Path) -> None:
    figures = Figures(FigureAnswer())
    reader = FootageReader(_run(), [_clip_view(_clean_ocr())])

    content = _footage_build(tmp_path, reader, figures)

    assert content.footage_status == "ok" and len(content.footage) == 1
    item = content.footage[0]
    assert item.description == "A flooded street." and item.clip_start == 4.2
    assert (
        item.video.location.as_posix() == "reports/wf_a/footage/abc.mp4"
        and item.shows_object == "yes"
    )
    assert "A flooded street." in figures.prompts[0]


def test_more_than_six_stored_clips_are_capped(tmp_path: Path) -> None:
    reader = FootageReader(
        _run(),
        [
            replace(
                _clip_view(_clean_ocr()),
                url=f"https://www.tiktok.com/@broll/video/74000000000000000{n}",
                media_location=f"reports/wf_a/footage/clip{n}.mp4",
            )
            for n in range(7)
        ],
    )
    content = _footage_build(tmp_path, reader)
    assert content.footage_status == "ok" and len(content.footage) == 6


def test_a_broken_stored_clip_is_left_out(tmp_path: Path) -> None:
    reader = FootageReader(_run(), [_clip_view({})])
    content = _footage_build(tmp_path, reader)
    assert (content.footage, content.footage_status) == ([], "none")
